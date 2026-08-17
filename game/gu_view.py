import asyncio
from typing import Optional

import discord

from . import equipment
from .base_view import GameView

# Highest quality first, matching this view's own "show your highest tier first" default --
# also the order the filter buttons themselves are laid out in (row 0: All + the top 3
# tiers, row 1: the bottom 4), so the button row reads high-to-low left-to-right too.
TIER_FILTER_ORDER = list(reversed(equipment.GU_QUALITY_ORDER))


class GuCollectionView(GameView):
    """/gu -- read-only display of every Gu you own (their quality and effect), sorted
    strongest-tier-first by default. Tier filter buttons narrow the list down to one quality
    at a time. No actions live here -- /upgrade_gu handles fusing/breaking down, /equipment
    handles equipping."""

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.tier_filter: Optional[str] = None  # None == "All"
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/gu` yourself to view your own collection.", ephemeral=True)
            return False
        return True

    def _equipped_gu_names(self) -> list:
        """Every currently-equipped Gu-type item name (normally just one, from "gu_ability" --
        Twin Gu Sovereign Physique unlocks a second slot, "gu_ability_2"). Read generically off
        equipment.SLOT_TYPE_BY_KEY rather than hardcoding "gu_ability" so this never needs
        touching again if a third Gu slot is ever added."""
        equipped = self.game.get_equipped(self.user_id)
        return [
            item_name for slot_key, item_name in equipped.items()
            if equipment.SLOT_TYPE_BY_KEY.get(slot_key) == "Gu"
        ]

    def _owned(self) -> list:
        """[(family, quality, item_name, qty, instance), ...] -- every owned Gu with a
        resolvable quality tier (flat/non-tiered Gu, e.g. the 3 starters and World Boss's flat
        drops, have never shown up in /gu -- this view keeps that existing behavior unchanged).
        `instance` is None for an ordinary quantity-stacked catalog entry, or the gu_instances
        row for a Hairy-Man-blessed copy (see game/grotto.py) -- those are never inventory-
        tracked (owning the row IS owning the piece, same as crafted_gear), so they're listed
        separately here rather than folded into the plain inventory counts above. Equipping a
        Gu moves it OUT of inventory into the equipped table, so the currently-worn one(s)
        wouldn't show up at all without adding them back in here."""
        inventory = self.game.get_inventory(self.user_id)
        counts = {name: qty for name, qty in inventory.items() if equipment.parse_gu_name(name)[0] is not None}
        for equipped_gu in self._equipped_gu_names():
            if equipment.parse_gu_name(equipped_gu)[0] is not None:
                counts[equipped_gu] = counts.get(equipped_gu, 0) + 1
        owned = []
        for item_name, qty in counts.items():
            family, quality = equipment.parse_gu_name(item_name)
            owned.append((family, quality, item_name, qty, None))
        for instance in self.game.db.get_player_gu_instances(self.user_id):
            family, quality = equipment.parse_gu_name(instance["item_name"])
            if family is None:
                continue
            owned.append((family, quality, instance["item_name"], 1, instance))
        return owned

    def _filtered_sorted(self) -> list:
        owned = self._owned()
        if self.tier_filter:
            owned = [row for row in owned if row[1] == self.tier_filter]
        # Highest tier first (per explicit request), family name as the tiebreaker within a
        # tier for stable, readable ordering.
        owned.sort(key=lambda row: (-equipment.GU_QUALITY_ORDER.index(row[1]), row[0]))
        return owned

    def _build_components(self):
        self.clear_items()
        all_button = discord.ui.Button(
            label="All", row=0, style=discord.ButtonStyle.primary if self.tier_filter is None else discord.ButtonStyle.secondary,
        )
        all_button.disabled = self.tier_filter is None
        all_button.callback = self._make_filter_callback(None)
        self.add_item(all_button)

        for index, quality in enumerate(TIER_FILTER_ORDER):
            button = discord.ui.Button(
                label=quality, row=(index + 1) // 4,
                style=discord.ButtonStyle.primary if quality == self.tier_filter else discord.ButtonStyle.secondary,
            )
            button.disabled = quality == self.tier_filter
            button.callback = self._make_filter_callback(quality)
            self.add_item(button)

    def _make_filter_callback(self, quality: Optional[str]):
        async def callback(interaction: discord.Interaction):
            self.tier_filter = quality
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    def build_embed(self) -> discord.Embed:
        equipped_gu_names = set(self._equipped_gu_names())
        owned = self._filtered_sorted()

        title_suffix = f" — {self.tier_filter}" if self.tier_filter else ""
        embed = discord.Embed(title=f"🐛 {self.display_name}'s Gu Collection{title_suffix}", color=discord.Color.dark_teal())
        if owned:
            equipped_instance_ids = set(self.game.db.get_equipped_gu_instance_ids(self.user_id).values())
            lines = []
            for family, quality, item_name, qty, instance in owned:
                gear = equipment.EQUIPMENT.get(item_name)
                base_stats = gear.stat_bonuses if gear else {}
                if instance:
                    marker = " ✅ equipped" if instance["instance_id"] in equipped_instance_ids else ""
                    combined = dict(base_stats)
                    for key, value in instance["bonus_stat_bonuses"].items():
                        combined[key] = combined.get(key, 0) + value
                    stats_text = equipment.describe_stat_bonuses(combined)
                    lines.append(f"🐒 **{item_name}** (Blessed +{instance['blessing_ticks']}){marker} — {stats_text}")
                else:
                    marker = " ✅ equipped" if item_name in equipped_gu_names else ""
                    stats_text = equipment.describe_stat_bonuses(base_stats)
                    lines.append(f"**{item_name}** x{qty}{marker} — {stats_text}")
            embed.description = "\n".join(lines)[:4000]
        elif self.tier_filter:
            embed.description = f"You don't own any {self.tier_filter}-quality Gu yet."
        else:
            embed.description = "You don't own any Gu yet — try `/hunt`, `/raid`, or `/explore`."
        embed.set_footer(text="Sorted strongest tier first. Use /upgrade_gu to fuse duplicates into a higher quality, /equipment to equip one.")
        return embed
