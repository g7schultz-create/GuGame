from collections import Counter
from typing import Optional

import discord

from . import equipment, gu_types, killer_move_gen
from .base_view import GameView
from .ui_utils import NAV_NEXT_VALUE, NAV_PREV_VALUE, paginate_select_options

TABS = [("assemble", "Assemble", "🧬"), ("moves", "My Killer Moves", "📖")]

KIND_LABEL = {
    "damage": "⚔️ Damage", "buff": "✨ Buff",
    "essence": "💧 Essence", "cultivation": "🌿 Cultivation", "loot": "🍀 Loot",
}


def _owned_gu_options(game, user_id: int, core_only: bool = False, rarity_filter: Optional[str] = None,
                       reserved: Optional[dict] = None, always_include: Optional[str] = None) -> list:
    """Every owned Gu matching the filters, strongest first -- the FULL list, uncapped (the
    caller pages it through ui_utils.paginate_select_options, same convention
    equipment_view.py's own Gu Ability picker already uses for this exact problem: a player
    who has amassed dozens of distinct Gu previously had everything past the 25 strongest
    silently invisible here with no way to reach it, even with the rarity filter narrowed --
    a heavy player can still own 25+ distinct Gu at a single quality tier). core_only
    additionally requires a resolvable quality tier (see equipment.parse_gu_name) -- only
    tiered/canon Gu can anchor a Killer Move as its core, since Mortal/Immortal is derived
    from that quality. rarity_filter, when set, only returns Gu at exactly that quality (a
    flat/non-tiered Gu has no quality at all, so it's excluded whenever a specific rarity is
    requested). reserved, when set, subtracts an already-committed count (Gu already picked
    as a component, or already spent on the core) from owned quantity -- once a name's owned
    copies are fully spoken for it drops out of the list entirely, so a Gu you've already used
    disappears from the dropdown instead of letting you pick more copies than you actually
    own. always_include forces one specific name back into the list even if fully reserved, so
    the currently selected core never vanishes from its own dropdown just because every
    remaining copy is already committed to components."""
    inventory = game.get_inventory(user_id)
    reserved = reserved or {}
    names = [
        name for name, item in equipment.EQUIPMENT.items()
        if item.slot_type == "Gu" and inventory.get(name, 0) - reserved.get(name, 0) > 0
        and (not core_only or equipment.parse_gu_name(name)[1] is not None)
        and (rarity_filter is None or equipment.parse_gu_name(name)[1] == rarity_filter)
    ]
    names.sort(key=lambda name: -equipment.gear_power_score(equipment.EQUIPMENT[name]))
    if always_include and always_include not in names:
        names.insert(0, always_include)
    return names


def _gu_option_label(name: str, remaining: int) -> str:
    return f"{name} (x{max(0, remaining)} left)"[:100]


def _gu_option_description(name: str) -> str:
    """What picking this Gu contributes -- its type (matches against the core Gu's type raise
    harmony) and which move kind that type leans toward (see gu_types.TYPE_AFFINITY), so a
    player can tell at a glance what a component will do without leaving /killer_move."""
    gu_type = gu_types.gu_type_for(name)
    if gu_type is None:
        return "Unknown type"
    affinity = gu_types.TYPE_AFFINITY.get(gu_type)
    kind_text = KIND_LABEL[affinity].split(" ", 1)[1] if affinity else "?"
    return f"{gu_type.title()} type — leans {kind_text}"


class KillerMoveView(GameView):
    """/killer_move -- assemble a core Gu + 10 component Gu into a procedurally-generated
    active ability (see game/killer_move_gen.py), additive alongside the existing Gu Ability
    equipment slot. Two tabs: Assemble (pick core + 10 components, live harmony/kind preview,
    commit) and My Killer Moves (equip/unequip either slot from what's already been assembled)."""

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.active_tab = "assemble"
        self.target_slot = "combat"
        self.rarity_filter: Optional[str] = None  # None == "All Rarities"
        self.core_page = 0
        self.component_page = 0
        self.core_gu_name: Optional[str] = None
        self.component_gu_names: list = []
        self.selected_move_id: Optional[int] = None
        self.last_result: Optional[str] = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your Killer Move workshop.", ephemeral=True)
            return False
        return True

    # -- shared preview math (no DB writes) -----------------------------------------------

    def _preview(self):
        """Returns None if core+10 components aren't both chosen yet, else a dict mirroring
        exactly what assemble_killer_move will compute (same functions, same order) so this
        preview never drifts from what committing actually produces."""
        if self.core_gu_name is None or len(self.component_gu_names) != 10:
            return None
        primary_type = gu_types.gu_type_for(self.core_gu_name)
        component_types = [gu_types.gu_type_for(n) for n in self.component_gu_names]
        harmony = killer_move_gen.calculate_harmony(primary_type, component_types)
        kind = killer_move_gen.dominant_kind(component_types, primary_type)
        band = killer_move_gen._harmony_band(harmony)
        return {"primary_type": primary_type, "harmony": harmony, "kind": kind, "band": band}

    # -- component build -------------------------------------------------------------------

    def _build_components(self):
        self.clear_items()
        for tab_key, label, emoji in TABS:
            button = discord.ui.Button(label=label, emoji=emoji, row=0, style=discord.ButtonStyle.primary if tab_key == self.active_tab else discord.ButtonStyle.secondary)
            button.disabled = tab_key == self.active_tab
            button.callback = self._make_tab_callback(tab_key)
            self.add_item(button)

        if self.active_tab == "assemble":
            self._build_assemble_components()
        else:
            self._build_moves_components()

    def _build_assemble_components(self):
        # Rarity filter -- a Select (not buttons: "All" + 7 qualities would badly overflow
        # Discord's 5-per-row button cap) so it fits one row regardless of option count, same
        # fix accessories_view.py's own type filter just applied for this exact shape. Row 1
        # is free for it because the Target: Combat/Support toggle below moved onto row 4
        # (this view was already using all 5 rows, so something had to move to make room).
        rarity_options = [discord.SelectOption(label="All Rarities", value="all", default=self.rarity_filter is None)]
        for quality in equipment.GU_QUALITY_ORDER:
            rarity_options.append(discord.SelectOption(label=quality, value=quality, default=(quality == self.rarity_filter)))
        rarity_select = discord.ui.Select(placeholder="Filter by rarity...", options=rarity_options, row=1)
        rarity_select.callback = self._on_pick_rarity
        self.add_item(rarity_select)

        # Reserve what's already spoken for in the current in-progress pick, so a Gu you've
        # already added as a component (or set as the core) shrinks or disappears from these
        # dropdowns once you're out of owned copies -- rather than letting you pick the same
        # Gu more times than you actually own (the bug: repeatedly selecting one Mythic Gu for
        # all 10 component slots from a dropdown that never reflected what had already been used).
        inventory = self.game.get_inventory(self.user_id)
        component_counts = Counter(self.component_gu_names)

        core_reserved = dict(component_counts)
        core_names = _owned_gu_options(
            self.game, self.user_id, core_only=True, rarity_filter=self.rarity_filter,
            reserved=core_reserved, always_include=self.core_gu_name,
        )
        core_options = [
            discord.SelectOption(
                label=_gu_option_label(name, inventory.get(name, 0) - core_reserved.get(name, 0)),
                value=name, description=_gu_option_description(name), default=(name == self.core_gu_name),
            )
            for name in core_names
        ]
        # Paginated the same way equipment_view.py's own Gu Ability picker already solves this
        # exact problem -- a player who has amassed dozens of distinct Gu (real accounts on
        # this server own 75+) previously had everything past the 25 strongest silently
        # unreachable here, even narrowed by rarity (a heavy player can own 25+ distinct Gu at
        # a single quality tier alone).
        core_page_options, core_total_pages, self.core_page = paginate_select_options(core_options, self.core_page)
        core_placeholder = f"Core Gu: {self.core_gu_name}" if self.core_gu_name else "Choose your core Gu..."
        if core_total_pages > 1:
            core_placeholder += f" (page {self.core_page + 1}/{core_total_pages})"
        core_select = discord.ui.Select(
            placeholder=core_placeholder,
            options=core_page_options or [discord.SelectOption(label="No eligible Gu owned at this rarity", value="none")],
            disabled=not core_options, row=2,
        )
        core_select.callback = self._on_pick_core
        self.add_item(core_select)

        component_reserved = dict(component_counts)
        if self.core_gu_name:
            component_reserved[self.core_gu_name] = component_reserved.get(self.core_gu_name, 0) + 1
        component_names = _owned_gu_options(
            self.game, self.user_id, core_only=False, rarity_filter=self.rarity_filter,
            reserved=component_reserved,
        )
        component_options = [
            discord.SelectOption(
                label=_gu_option_label(name, inventory.get(name, 0) - component_reserved.get(name, 0)),
                value=name, description=_gu_option_description(name),
            )
            for name in component_names
        ]
        component_page_options, component_total_pages, self.component_page = paginate_select_options(component_options, self.component_page)
        remaining = 10 - len(self.component_gu_names)
        component_placeholder = f"Add a component Gu ({len(self.component_gu_names)}/10 chosen)..." if remaining > 0 else "10/10 chosen -- ready to assemble"
        if component_total_pages > 1:
            component_placeholder += f" (page {self.component_page + 1}/{component_total_pages})"
        component_select = discord.ui.Select(
            placeholder=component_placeholder,
            options=component_page_options or [discord.SelectOption(label="No more copies available at this rarity", value="none")],
            disabled=not component_options or remaining <= 0, row=3,
        )
        component_select.callback = self._on_pick_component
        self.add_item(component_select)

        # Target slot, Remove Last, Clear, and Assemble all share row 4 (5 buttons total, the
        # max Discord allows) now that the rarity filter above claimed row 1.
        for slot_key, label in (("combat", "Combat"), ("support", "Support")):
            button = discord.ui.Button(label=f"Target: {label}", row=4, style=discord.ButtonStyle.primary if slot_key == self.target_slot else discord.ButtonStyle.secondary)
            button.disabled = slot_key == self.target_slot
            button.callback = self._make_slot_callback(slot_key)
            self.add_item(button)

        remove_button = discord.ui.Button(label="Remove Last", emoji="↩️", row=4, disabled=not self.component_gu_names)
        remove_button.callback = self._on_remove_last
        self.add_item(remove_button)

        clear_button = discord.ui.Button(label="Clear", emoji="🗑️", row=4, disabled=not self.component_gu_names and self.core_gu_name is None)
        clear_button.callback = self._on_clear
        self.add_item(clear_button)

        preview = self._preview()
        expected_kinds = ("damage", "buff") if self.target_slot == "combat" else ("essence", "cultivation", "loot")
        can_assemble = preview is not None and preview["kind"] in expected_kinds
        assemble_button = discord.ui.Button(label="Assemble", emoji="🔥", style=discord.ButtonStyle.success, row=4, disabled=not can_assemble)
        assemble_button.callback = self._on_assemble
        self.add_item(assemble_button)

    def _build_moves_components(self):
        moves = self.game.get_player_killer_moves(self.user_id)
        move_options = [
            discord.SelectOption(
                label=f"{move['name']} ({move['move_tier']}, {KIND_LABEL[move['kind']].split(' ')[1]})"[:100],
                value=str(move["killer_move_id"]), default=(move["killer_move_id"] == self.selected_move_id),
            )
            for move in moves
        ]
        move_select = discord.ui.Select(
            placeholder="Choose a Killer Move...",
            options=move_options[:25] or [discord.SelectOption(label="None assembled yet", value="none")],
            disabled=not move_options, row=1,
        )
        move_select.callback = self._on_pick_move
        self.add_item(move_select)

        selected = next((m for m in moves if m["killer_move_id"] == self.selected_move_id), None)
        # A move's slot (combat vs support) is fixed at assembly time (see
        # assemble_killer_move's dominant-kind validation), so equipping only ever needs one
        # button -- equip_killer_move already knows which of the two slots to fill from the
        # move's own stored `slot` field.
        equip_label = f"Equip ({selected['slot'].title()})" if selected else "Equip"
        equip_button = discord.ui.Button(label=equip_label, emoji="⚔️", style=discord.ButtonStyle.success, row=2, disabled=selected is None)
        equip_button.callback = self._on_equip
        self.add_item(equip_button)

        unequip_combat = discord.ui.Button(label="Unequip Combat", emoji="🗑️", row=2)
        unequip_combat.callback = self._make_unequip_callback("combat")
        self.add_item(unequip_combat)

        unequip_support = discord.ui.Button(label="Unequip Support", emoji="🗑️", row=2)
        unequip_support.callback = self._make_unequip_callback("support")
        self.add_item(unequip_support)

    # -- callbacks --------------------------------------------------------------------------

    def _make_tab_callback(self, tab_key: str):
        async def callback(interaction: discord.Interaction):
            self.active_tab = tab_key
            self.last_result = None
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        return callback

    def _make_slot_callback(self, slot_key: str):
        async def callback(interaction: discord.Interaction):
            self.target_slot = slot_key
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        return callback

    async def _on_pick_rarity(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        value = select.values[0]
        # Only narrows what the core/component Selects OFFER next -- doesn't clear a core/
        # components you've already picked, same non-destructive convention the Target: Combat/
        # Support toggle already follows.
        self.rarity_filter = None if value == "all" else value
        self.core_page = 0
        self.component_page = 0
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_pick_core(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        value = select.values[0]
        if value == NAV_PREV_VALUE:
            self.core_page = max(0, self.core_page - 1)
        elif value == NAV_NEXT_VALUE:
            self.core_page += 1
        else:
            self.core_gu_name = None if value == "none" else value
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_pick_component(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 3)
        value = select.values[0]
        if value == NAV_PREV_VALUE:
            self.component_page = max(0, self.component_page - 1)
        elif value == NAV_NEXT_VALUE:
            self.component_page += 1
        elif value != "none" and len(self.component_gu_names) < 10:
            self.component_gu_names.append(value)
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_remove_last(self, interaction: discord.Interaction):
        if self.component_gu_names:
            self.component_gu_names.pop()
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_clear(self, interaction: discord.Interaction):
        self.core_gu_name = None
        self.component_gu_names = []
        self.core_page = 0
        self.component_page = 0
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_assemble(self, interaction: discord.Interaction):
        result = self.game.assemble_killer_move(
            self.user_id, self.display_name, self.target_slot, self.core_gu_name, self.component_gu_names,
        )
        if result["ok"]:
            move = result["killer_move"]
            self.last_result = f"✅ Assembled **{move['name']}** ({move['move_tier']}, {KIND_LABEL[move['kind']]}, harmony {move['harmony']})! See My Killer Moves to equip it."
            self.core_gu_name = None
            self.component_gu_names = []
        else:
            self.last_result = f"❌ {result['reason']}"
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_pick_move(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        value = select.values[0]
        self.selected_move_id = None if value == "none" else int(value)
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_equip(self, interaction: discord.Interaction):
        ok, message = self.game.equip_killer_move(self.user_id, self.display_name, self.selected_move_id)
        self.last_result = message
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def _make_unequip_callback(self, slot: str):
        async def callback(interaction: discord.Interaction):
            ok, message = self.game.unequip_killer_move(self.user_id, self.display_name, slot)
            self.last_result = message
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        return callback

    # -- embed --------------------------------------------------------------------------

    def _effects_text(self, kind: str, effects: dict) -> str:
        if kind == "damage":
            return f"**{effects['str_multiplier']:.2f}x** STR/ATK damage"
        if kind == "buff":
            parts = [f"+{v * 100:.1f}% {k.replace('_pct', '').upper()}" for k, v in effects.items() if k != "duration_seconds"]
            return f"{', '.join(parts)} for {effects['duration_seconds'] // 60} min"
        if kind == "essence":
            return f"Restores **{effects['pct'] * 100:.1f}%** of max primeval essence"
        label = "cultivation speed" if kind == "cultivation" else "loot luck"
        return f"+{effects['pct'] * 100:.1f}% {label} for {effects['duration_seconds'] // 60} min"

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(title=f"🌀 {self.display_name}'s Killer Moves", color=discord.Color.dark_purple())
        if self.active_tab == "assemble":
            rarity_text = f", rarity **{self.rarity_filter}**" if self.rarity_filter else ""
            embed.description = (
                f"Target slot: **{self.target_slot.title()}**{rarity_text}. Pick a core Gu (sets tier/flavor) and exactly "
                "10 component Gu -- all 11 are permanently consumed on Assemble. Each Gu's dropdown entry shows its type "
                "and which move kind it leans toward: components sharing the core's type raise **harmony** (higher = "
                "stronger move), and whichever kind most of your 10 components lean toward becomes the move's actual kind."
            )
            embed.add_field(name="Core Gu", value=self.core_gu_name or "*(none chosen)*", inline=False)
            component_text = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(self.component_gu_names)) or "*(none chosen)*"
            embed.add_field(name=f"Components ({len(self.component_gu_names)}/10)", value=component_text[:1024], inline=False)
            preview = self._preview()
            if preview:
                embed.add_field(
                    name="Preview",
                    value=(
                        f"Type: **{preview['primary_type']}** • Harmony: **{preview['harmony']}** ({preview['band'].label}, "
                        f"{preview['band'].power_multiplier:.2f}x) • Kind: **{KIND_LABEL[preview['kind']]}**"
                    ),
                    inline=False,
                )
        else:
            player = self.game.get_player_stats(self.user_id, self.display_name)
            for slot in ("combat", "support"):
                move = self.game.get_equipped_killer_move(player, slot)
                if move:
                    qi_cost = self.game.killer_move_qi_cost(player, move)
                    value = (
                        f"**{move['name']}** ({move['move_tier']}, {KIND_LABEL[move['kind']]})\n"
                        f"{self._effects_text(move['kind'], move['effects'])}\nQi cost: **{qi_cost:,}**"
                    )
                else:
                    value = "*(none equipped)*"
                embed.add_field(name=f"{slot.title()} Slot", value=value, inline=False)
            moves = self.game.get_player_killer_moves(self.user_id)
            if not moves:
                embed.add_field(name="Assembled Killer Moves", value="You haven't assembled any yet -- see the Assemble tab.", inline=False)
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result[:1024], inline=False)
        return embed
