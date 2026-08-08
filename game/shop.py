import asyncio
import discord

from . import chargen
from .base_view import GameView
from .character_data import PHYSIQUE_TIER_ORDER, PHYSIQUE_TIERS, ROOT_TIER_ORDER, ROOT_TIERS


def _format_current(tier_name, item_name, tiers_catalog) -> str:
    tier = tiers_catalog.get(tier_name) if tier_name else None
    if not tier:
        return "Not rolled yet."
    value = f"{tier.emoji} **{item_name}** ({tier.name})\n" + "\n".join(tier.display_bonuses)
    if tier.passive:
        value += f"\nPassive: {tier.passive}"
    unique = chargen.unique_passive(tiers_catalog, tier_name, item_name)
    if unique:
        value += f"\n✨ {unique}"
    return value


def _format_batch_result(label: str, rolls: list, hit_target: bool, target_tier: str) -> str:
    tier_counts = ", ".join(f"{tier}" for tier, _ in rolls)
    if hit_target:
        return f"🎯 {label}: rolled {len(rolls)}x, hit **{target_tier}+** on roll {len(rolls)} — {tier_counts}."
    return f"{label}: rolled {len(rolls)}x without reaching **{target_tier}** — best was **{_best_roll(rolls)[0]}**. All rolls: {tier_counts}."


def _best_roll(rolls: list):
    """The single highest-rarity roll in the batch — the pending candidate offered whether
    the target was hit (in which case it's always the roll that stopped the batch — nothing
    earlier could have out-ranked it without stopping the batch itself) or not (in which case
    it's whatever's best of the 10, not just whatever happened to come up last)."""
    return max(rolls, key=lambda roll: ROOT_TIER_ORDER.index(roll[0]))


class ShopView(GameView):
    DEFAULT_TARGET_TIER = "Legendary"

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.last_result: str = None
        # A rolled-but-undecided candidate: (tier, name) or None. Paid for at roll time;
        # the player then picks whether to actually take it or keep what they had.
        self.pending_root = None
        self.pending_physique = None
        # Which tier "Roll x10" stops early on (see GameManager._buy_reroll_batch — stops on
        # this tier OR RARER, not an exact match).
        self.root_target_tier = self.DEFAULT_TARGET_TIER
        self.physique_target_tier = self.DEFAULT_TARGET_TIER
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your shop.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        player = self.game.get_player_stats(self.user_id, self.display_name)
        stones = player["spirit_stones"]

        root_cost = self.game.SHOP_ROOT_REROLL_COST
        physique_cost = self.game.SHOP_PHYSIQUE_REROLL_COST

        root_target_select = discord.ui.Select(
            placeholder=f"Root: stop rolling at {self.root_target_tier}+...",
            options=[
                discord.SelectOption(label=tier, value=tier, default=(tier == self.root_target_tier))
                for tier in ROOT_TIER_ORDER
            ],
            row=0,
        )
        root_target_select.callback = self._on_pick_root_target
        self.add_item(root_target_select)

        root_locked = self.pending_root is not None
        root_button = discord.ui.Button(
            label=f"Reroll Root ({root_cost:,} 🪙)", emoji="🌱", style=discord.ButtonStyle.primary,
            disabled=stones < root_cost or root_locked, row=1,
        )
        root_button.callback = self._on_buy_root
        self.add_item(root_button)

        root_batch_button = discord.ui.Button(
            label=f"Roll x{self.game.SHOP_BATCH_ROLL_COUNT} Root", emoji="🎲", style=discord.ButtonStyle.primary,
            disabled=stones < root_cost or root_locked, row=1,
        )
        root_batch_button.callback = self._on_buy_root_batch
        self.add_item(root_batch_button)

        if self.pending_root:
            _, root_name = self.pending_root
            keep_button = discord.ui.Button(label="Keep Old Root", emoji="↩️", style=discord.ButtonStyle.secondary, row=1)
            keep_button.callback = self._on_keep_old_root
            self.add_item(keep_button)
            take_button = discord.ui.Button(label=f"Take New Root ({root_name})", emoji="✅", style=discord.ButtonStyle.success, row=1)
            take_button.callback = self._on_take_new_root
            self.add_item(take_button)

        physique_target_select = discord.ui.Select(
            placeholder=f"Physique: stop rolling at {self.physique_target_tier}+...",
            options=[
                discord.SelectOption(label=tier, value=tier, default=(tier == self.physique_target_tier))
                for tier in PHYSIQUE_TIER_ORDER
            ],
            row=2,
        )
        physique_target_select.callback = self._on_pick_physique_target
        self.add_item(physique_target_select)

        physique_locked = self.pending_physique is not None
        physique_button = discord.ui.Button(
            label=f"Reroll Physique ({physique_cost:,} 🪙)", emoji="💪", style=discord.ButtonStyle.primary,
            disabled=stones < physique_cost or physique_locked, row=3,
        )
        physique_button.callback = self._on_buy_physique
        self.add_item(physique_button)

        physique_batch_button = discord.ui.Button(
            label=f"Roll x{self.game.SHOP_BATCH_ROLL_COUNT} Physique", emoji="🎲", style=discord.ButtonStyle.primary,
            disabled=stones < physique_cost or physique_locked, row=3,
        )
        physique_batch_button.callback = self._on_buy_physique_batch
        self.add_item(physique_batch_button)

        if self.pending_physique:
            _, physique_name = self.pending_physique
            keep_button = discord.ui.Button(label="Keep Old Physique", emoji="↩️", style=discord.ButtonStyle.secondary, row=3)
            keep_button.callback = self._on_keep_old_physique
            self.add_item(keep_button)
            take_button = discord.ui.Button(label=f"Take New Physique ({physique_name})", emoji="✅", style=discord.ButtonStyle.success, row=3)
            take_button.callback = self._on_take_new_physique
            self.add_item(take_button)

    async def _on_pick_root_target(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        self.root_target_tier = select.values[0]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_physique_target(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        self.physique_target_tier = select.values[0]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_buy_root(self, interaction: discord.Interaction):
        ok, tier, name = await asyncio.to_thread(self.game.buy_root_reroll, self.user_id, self.display_name)
        if ok:
            self.pending_root = (tier, name)
            self.last_result = f"🌱 Rolled a candidate Root: **{name}** ({tier}) — keep it or stick with your old one."
        else:
            self.last_result = "Not enough spirit stones."
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_buy_root_batch(self, interaction: discord.Interaction):
        rolls, hit_target = await asyncio.to_thread(
            self.game.buy_root_reroll_batch, self.user_id, self.display_name, self.root_target_tier,
        )
        if not rolls:
            self.last_result = "Not enough spirit stones."
        else:
            self.pending_root = _best_roll(rolls)
            self.last_result = _format_batch_result("🌱 Root", rolls, hit_target, self.root_target_tier)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_keep_old_root(self, interaction: discord.Interaction):
        self.pending_root = None
        self.last_result = "Kept your old Root."
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_take_new_root(self, interaction: discord.Interaction):
        tier, name = self.pending_root
        await asyncio.to_thread(self.game.db.set_root, self.user_id, tier, name)
        self.pending_root = None
        self.last_result = f"🌱 Took the new Root: **{name}** ({tier})!"
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_buy_physique(self, interaction: discord.Interaction):
        ok, tier, name = await asyncio.to_thread(self.game.buy_physique_reroll, self.user_id, self.display_name)
        if ok:
            self.pending_physique = (tier, name)
            self.last_result = f"💪 Rolled a candidate Physique: **{name}** ({tier}) — keep it or stick with your old one."
        else:
            self.last_result = "Not enough spirit stones."
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_buy_physique_batch(self, interaction: discord.Interaction):
        rolls, hit_target = await asyncio.to_thread(
            self.game.buy_physique_reroll_batch, self.user_id, self.display_name, self.physique_target_tier,
        )
        if not rolls:
            self.last_result = "Not enough spirit stones."
        else:
            self.pending_physique = _best_roll(rolls)
            self.last_result = _format_batch_result("💪 Physique", rolls, hit_target, self.physique_target_tier)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_keep_old_physique(self, interaction: discord.Interaction):
        self.pending_physique = None
        self.last_result = "Kept your old Physique."
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_take_new_physique(self, interaction: discord.Interaction):
        tier, name = self.pending_physique
        await asyncio.to_thread(self.game.db.set_physique, self.user_id, tier, name)
        self.pending_physique = None
        self.last_result = f"💪 Took the new Physique: **{name}** ({tier})!"
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def build_embed(self) -> discord.Embed:
        player = self.game.get_player_stats(self.user_id, self.display_name)
        embed = discord.Embed(
            title="🛒 Shop",
            description="Spend spirit stones to reroll your Root or Physique — no limit, unlike your free `/join` rerolls. "
            "A reroll costs a stone whether you keep it or not; you always get to choose. "
            f"**Roll x{self.game.SHOP_BATCH_ROLL_COUNT}** rolls one at a time and stops the moment it hits your chosen "
            "tier (or anything rarer) — pick your target from the dropdown first. Didn't hit it? You're still "
            "offered the best roll out of the batch, not just whichever one happened to land last.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="🪙 Spirit Stones", value=f"{player['spirit_stones']:,}", inline=False)
        embed.add_field(name="🌱 Current Root", value=_format_current(player["root_tier"], player["root_name"], ROOT_TIERS), inline=False)
        if self.pending_root:
            tier, name = self.pending_root
            embed.add_field(name="🆕 Candidate Root", value=_format_current(tier, name, ROOT_TIERS), inline=False)
        embed.add_field(name="💪 Current Physique", value=_format_current(player["physique_tier"], player["physique_name"], PHYSIQUE_TIERS), inline=False)
        if self.pending_physique:
            tier, name = self.pending_physique
            embed.add_field(name="🆕 Candidate Physique", value=_format_current(tier, name, PHYSIQUE_TIERS), inline=False)
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        return embed
