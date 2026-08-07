import discord

from . import blacksmith
from .base_view import GameView
from .equipment import SLOT_TYPE_EMOJI, describe_stat_bonuses

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

    async def _on_pick_gear(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        value = select.values[0]
        self.selected_gear_id = int(value) if value != "none" else None
        self.last_result = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_dismantle(self, interaction: discord.Interaction):
        ok, message = self.game.dismantle_crafted_gear(self.user_id, self.display_name, self.selected_gear_id)
        self.last_result = message
        self.selected_gear_id = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

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
                    lines.append(f"{marker}**{display_name}** — {describe_stat_bonuses(g['stat_bonuses'])} (Power {g['power_score']:.1f})")
            else:
                lines.append("　*(none)*")
            sections.append("\n".join(lines))

        embed.description = "\n\n".join(sections)[:4000]
        embed.set_footer(text="✅ = currently equipped. Pick a piece below to dismantle it for a partial materials refund (unequip it first).")
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        return embed
