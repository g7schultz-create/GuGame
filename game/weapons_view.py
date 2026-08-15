import asyncio

import discord

from . import blacksmith
from .base_view import GameView
from .equipment import SLOT_TYPE_EMOJI, describe_stat_bonuses
from .ui_utils import format_number

# Fixed display order — matches the order these three slots appear in equipment.SLOTS.
SLOT_TYPE_ORDER = ["Weapon", "Head", "Body"]


class WeaponsView(GameView):
    """/weapons: a text-document-style listing of every rolled crafted_gear instance you
    own (see database.py's crafted_gear table) — each one has its own unique id and randomly
    rolled stats, unlike the rest of this game's stackable catalog equipment. Also the home
    of dismantling a piece you don't want for a partial materials refund."""

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.selected_gear_id: int = None
        self.last_result: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/weapons` yourself to manage your own gear.", ephemeral=True)
            return False
        return True

    def _owned(self) -> list:
        return self.game.get_player_crafted_gear(self.user_id)

    def _equipped_gear_ids(self) -> set:
        return set(self.game.db.get_equipped_gear_ids(self.user_id).values())

    def _same_tier_gear_ids(self, slot_type: str, tier: int) -> list:
        """Every OTHER owned, unequipped piece sharing the selected piece's exact
        slot_type+tier -- same grouping sell_view.SellView._same_tier_gear_ids already uses
        for its own "Sell All T{tier}" button, since repeated /blacksmith attempts are the
        main source of unwanted duplicate rolls at one tier."""
        equipped_ids = self._equipped_gear_ids()
        return [
            g["gear_id"] for g in self._owned()
            if g["slot_type"] == slot_type and g["tier"] == tier and g["gear_id"] not in equipped_ids
        ]

    def _build_components(self):
        self.clear_items()
        equipped_ids = self._equipped_gear_ids()
        # Dismantling an equipped piece always fails server-side (see
        # GameManager.dismantle_crafted_gear), so it's left off this list entirely rather
        # than offered as a dead-end option.
        dismantle_candidates = [g for g in self._owned() if g["gear_id"] not in equipped_ids]

        options = [
            discord.SelectOption(
                label=blacksmith.crafted_gear_display_name(g["base_type"], g["tier"], g["gear_id"])[:100],
                value=str(g["gear_id"]),
                description=describe_stat_bonuses(g["stat_bonuses"])[:100],
                default=(g["gear_id"] == self.selected_gear_id),
            )
            for g in dismantle_candidates[:25]
        ]
        select = discord.ui.Select(
            placeholder="Choose a piece to dismantle..." if options else "Nothing available to dismantle (unequip something first?)",
            options=options or [discord.SelectOption(label="None", value="none")],
            disabled=not options,
            row=0,
        )
        select.callback = self._on_pick_gear
        self.add_item(select)

        dismantle_button = discord.ui.Button(
            label="Dismantle", emoji="🔨", style=discord.ButtonStyle.danger, row=1,
            disabled=self.selected_gear_id is None,
        )
        dismantle_button.callback = self._on_dismantle
        self.add_item(dismantle_button)

        selected_gear = next((g for g in dismantle_candidates if g["gear_id"] == self.selected_gear_id), None)
        same_tier = self._same_tier_gear_ids(selected_gear["slot_type"], selected_gear["tier"]) if selected_gear else []
        dismantle_all_button = discord.ui.Button(
            label=f"Dismantle All T{selected_gear['tier']} {selected_gear['slot_type']} ({len(same_tier)})" if selected_gear else "Dismantle All",
            emoji="🧹", style=discord.ButtonStyle.secondary, row=1,
            disabled=len(same_tier) <= 1,
        )
        dismantle_all_button.callback = self._on_dismantle_all
        self.add_item(dismantle_all_button)

    async def _on_pick_gear(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        value = select.values[0]
        self.selected_gear_id = int(value) if value != "none" else None
        self.last_result = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_dismantle(self, interaction: discord.Interaction):
        ok, message = await asyncio.to_thread(self.game.dismantle_crafted_gear, self.user_id, self.display_name, self.selected_gear_id)
        self.last_result = message
        self.selected_gear_id = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_dismantle_all(self, interaction: discord.Interaction):
        """Bulk-dismantles every owned, unequipped piece sharing the selected piece's exact
        slot_type+tier in one click -- reuses dismantle_crafted_gear one instance at a time
        (it already re-checks ownership/equipped per call) rather than a new bulk backend
        method, same reasoning as sell_view.SellView._on_sell_all_same_tier, whose "Sell All
        T{tier}" button this mirrors directly for /weapons' own Dismantle button."""
        # Deferred since a big same-tier stack (many /blacksmith attempts at one tier) can add
        # up to real DB work across several dismantle_crafted_gear calls -- same defer-before-
        # the-loop fix already applied to Inventory's Use All / Alchemy's Make All.
        await interaction.response.defer()
        gear = await asyncio.to_thread(self.game.db.get_crafted_gear, self.selected_gear_id) if self.selected_gear_id else None
        if gear is None:
            self.last_result = "That item is no longer available."
        else:
            slot_type, tier = gear["slot_type"], gear["tier"]
            targets = await asyncio.to_thread(self._same_tier_gear_ids, slot_type, tier)
            count = 0
            for gid in targets:
                ok, _ = await asyncio.to_thread(self.game.dismantle_crafted_gear, self.user_id, self.display_name, gid)
                if ok:
                    count += 1
            stones = count * blacksmith.dismantle_stones(tier)
            self.last_result = (
                f"Dismantled {count}x Tier {tier} {slot_type} pieces — recovered materials + {format_number(stones)} 🪙 total."
                if count else "Nothing left to dismantle at that tier."
            )
        self.selected_gear_id = None
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.edit_original_response(embed=embed, view=self)

    def build_embed(self) -> discord.Embed:
        owned = self._owned()
        equipped_ids = self._equipped_gear_ids()

        embed = discord.Embed(title=f"⚔️ {self.display_name}'s Weapons", color=discord.Color.dark_gold())
        if not owned:
            embed.description = "You haven't forged or found any weapons, head, or body gear yet — try `/blacksmith` or `/search`!"
            embed.set_footer(text="Every piece you forge or find is unique, with its own id and randomly rolled stats.")
            return embed

        by_slot = {slot_type: [] for slot_type in SLOT_TYPE_ORDER}
        for g in owned:
            by_slot.setdefault(g["slot_type"], []).append(g)

        sections = []
        for slot_type in SLOT_TYPE_ORDER:
            pieces = by_slot.get(slot_type, [])
            emoji = SLOT_TYPE_EMOJI.get(slot_type, "•")
            lines = [f"{emoji} **{slot_type}**"]
            if pieces:
                for g in pieces:
                    marker = "✅ " if g["gear_id"] in equipped_ids else "　"
                    display_name = blacksmith.crafted_gear_display_name(g["base_type"], g["tier"], g["gear_id"])
                    lines.append(f"{marker}**{display_name}** — {describe_stat_bonuses(g['stat_bonuses'])} (Power {format_number(g['power_score'], decimals=1)})")
            else:
                lines.append("　*(none)*")
            sections.append("\n".join(lines))

        embed.description = "\n\n".join(sections)[:4000]
        embed.set_footer(text="✅ = currently equipped. Pick a piece below to dismantle it for a partial materials refund, or Dismantle All to clear out every duplicate at that same tier+slot at once (unequip first).")
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        return embed
