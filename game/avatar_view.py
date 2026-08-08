"""
AvatarView -- the /avatar menu: choose/reroll your Nascent Soul avatar's soul, equip its own
gear (a procedurally-rolled tier system, see game/avatar_gear.py -- drops from /rba and raid
bosses), and feed it Soul Nourishing Pills + Soul Crystals to level it up.
"""

import asyncio
import discord

from . import avatar, avatar_gear
from .base_view import GameView


class AvatarView(GameView):
    TABS = [("soul", "Soul", "🔮"), ("gear", "Gear", "🛡️"), ("levelup", "Level Up", "📈")]

    def __init__(self, user_id: int, game, display_name: str, avatar_url: str):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.avatar_url = avatar_url
        status = self._status()
        # Start on the Soul tab if nothing's been chosen yet (nowhere else makes sense to
        # land), otherwise Gear -- the tab a returning player is most likely here for.
        self.active_tab = "soul" if status["soul"] is None else "gear"
        self.selected_slot = avatar_gear.AVATAR_GEAR_SLOTS[0][0]
        self.last_result = None
        self.message: discord.Message = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your avatar.", ephemeral=True)
            return False
        return True

    def _status(self) -> dict:
        return self.game.get_avatar_status(self.user_id, self.display_name)

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

        status = self._status()
        if self.active_tab == "soul":
            self._build_soul_components(status)
        elif self.active_tab == "gear":
            self._build_gear_components(status)
        elif self.active_tab == "levelup":
            self._build_levelup_components(status)

    def _make_tab_callback(self, key: str):
        async def callback(interaction: discord.Interaction):
            self.active_tab = key
            self.last_result = None
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    def _build_soul_components(self, status: dict):
        current_name = status["soul"].name if status["soul"] else None
        options = [
            discord.SelectOption(
                label=f"{name}", emoji=soul.emoji,
                description=" / ".join(b.split(": ")[0].strip() for b in soul.display_bonuses)[:100],
                default=(name == current_name),
            )
            for name, soul in avatar.SOULS.items()
        ]
        select = discord.ui.Select(placeholder="Choose or reroll your avatar's soul", options=options[:25], row=1)
        select.callback = self._on_pick_soul
        self.add_item(select)

    def _build_gear_components(self, status: dict):
        if status["soul"] is None:
            return
        equipped = status["equipped"]
        slot_select = discord.ui.Select(
            placeholder=f"Slot: {avatar_gear.SLOT_LABEL_BY_KEY[self.selected_slot]}",
            options=[
                discord.SelectOption(
                    label=label, emoji=emoji, value=slot_key,
                    description=f"Current: {equipped.get(slot_key) or 'Empty'}"[:100],
                    default=(slot_key == self.selected_slot),
                )
                for slot_key, label, _, emoji in avatar_gear.AVATAR_GEAR_SLOTS
            ],
            row=1,
        )
        slot_select.callback = self._on_pick_slot
        self.add_item(slot_select)

        slot_type = avatar_gear.SLOT_TYPE_BY_KEY[self.selected_slot]
        equipped_instance_ids = self.game.get_avatar_equipped_instance_ids(self.user_id)
        currently_equipped_id = equipped_instance_ids.get(self.selected_slot)
        owned = [
            inst for inst in self.game.get_player_avatar_gear_instances(self.user_id)
            if inst["slot_type"] == slot_type and inst["instance_id"] != currently_equipped_id
        ]
        current_display = equipped.get(self.selected_slot)
        item_options = []
        if current_display:
            item_options.append(discord.SelectOption(label=f"Unequip {current_display}"[:100], value="__unequip__", emoji="🗑️"))
        for inst in owned:
            item_options.append(discord.SelectOption(
                label=f"{avatar_gear.tier_name(inst['tier'])} {slot_type} #{inst['instance_id']}"[:100],
                value=str(inst["instance_id"]),
                description=avatar_gear.describe_avatar_gear_stat_bonuses(inst["stat_bonuses"])[:100],
            ))
        item_select = discord.ui.Select(
            placeholder=f"Equip to {avatar_gear.SLOT_LABEL_BY_KEY[self.selected_slot]}",
            options=item_options[:25] or [discord.SelectOption(label="None available", value="none")],
            disabled=not item_options,
            row=2,
        )
        item_select.callback = self._on_pick_item
        self.add_item(item_select)

    def _build_levelup_components(self, status: dict):
        if status["soul"] is None:
            return
        recipe = status["next_recipe"]
        inventory = self.game.get_inventory(self.user_id)
        affordable = recipe is not None and all(inventory.get(item, 0) >= qty for item, qty in recipe.items())
        button = discord.ui.Button(
            label="Feed to Level Up" if recipe else "Max Level Reached",
            emoji="📈", style=discord.ButtonStyle.success, row=1,
            disabled=recipe is None or not affordable,
        )
        button.callback = self._on_level_up
        self.add_item(button)

    # -- action handlers ------------------------------------------------------------------

    async def _on_pick_soul(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        soul_name = select.values[0]
        status = await asyncio.to_thread(self._status)
        was_first_pick = status["soul"] is None
        ok, msg = await asyncio.to_thread(self.game.choose_avatar_soul, self.user_id, self.display_name, soul_name)
        self.last_result = msg
        if ok and was_first_pick:
            # Nowhere useful to look at right after your very first pick besides the gear you
            # just got auto-equipped -- flow straight there instead of leaving them on the
            # same Soul tab staring at the choice they just made.
            self.active_tab = "gear"
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_slot(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        self.selected_slot = select.values[0]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_item(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        value = select.values[0]
        if value == "none":
            await interaction.response.defer()
            return
        if value == "__unequip__":
            ok, msg = await asyncio.to_thread(self.game.unequip_avatar_gear_instance, self.user_id, self.display_name, self.selected_slot)
        else:
            ok, msg = await asyncio.to_thread(
                self.game.equip_avatar_gear_instance, self.user_id, self.display_name, self.selected_slot, int(value),
            )
        self.last_result = msg
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_level_up(self, interaction: discord.Interaction):
        ok, msg = await asyncio.to_thread(self.game.avatar_level_up, self.user_id, self.display_name)
        self.last_result = msg
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    # -- embed building ---------------------------------------------------------------

    def build_embed(self) -> discord.Embed:
        status = self._status()
        embed = discord.Embed(title="🌌 Nascent Soul Avatar", color=discord.Color.dark_purple())
        embed.set_thumbnail(url=self.avatar_url)

        if self.active_tab == "soul":
            self._fill_soul_embed(embed, status)
        elif self.active_tab == "gear":
            self._fill_gear_embed(embed, status)
        elif self.active_tab == "levelup":
            self._fill_levelup_embed(embed, status)

        if self.last_result:
            embed.add_field(name="Result", value=self.last_result, inline=False)
        return embed

    def _fill_soul_embed(self, embed: discord.Embed, status: dict):
        soul = status["soul"]
        if soul is None:
            embed.description = "Pick your avatar's soul below — this choice can be changed later for spirit stones."
            return
        embed.description = (
            f"{soul.emoji} **{soul.name}** — Level **{avatar.level_name(status['level'])}** • "
            f"Avatar Power **{status['power']:.1f}**\n{soul.tagline}"
        )
        embed.add_field(name=f"Passive — {soul.passive_name}", value=soul.passive_text, inline=False)
        embed.add_field(
            name=f"🌀 {avatar.SOUL_PROJECTION_NAME}",
            value=(
                f"{soul.ability_text}\n"
                f"*{avatar.SOUL_PROJECTION_QI_COST:,} battle Qi • {avatar.SOUL_PROJECTION_DURATION_TURNS} turns "
                f"— strikes immediately with the buff already active, usable in /hunt, /battlefield, and /raid "
                f"(passive-only in /raidboss_attack).*"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Rerolling your soul costs {self.game.AVATAR_SOUL_REROLL_COST:,} spirit stones.")

    def _fill_gear_embed(self, embed: discord.Embed, status: dict):
        if status["soul"] is None:
            embed.description = "Choose a soul first (Soul tab) — your avatar needs a soul before it can wear gear."
            return
        equipped = status["equipped"]
        equipped_instance_ids = self.game.get_avatar_equipped_instance_ids(self.user_id)
        lines = []
        for slot_key, label, _, emoji in avatar_gear.AVATAR_GEAR_SLOTS:
            instance_id = equipped_instance_ids.get(slot_key)
            instance = self.game.get_avatar_gear_instance(instance_id) if instance_id else None
            if instance:
                lines.append(
                    f"{emoji} **{label}**: {avatar_gear.tier_name(instance['tier'])} — "
                    f"{avatar_gear.describe_avatar_gear_stat_bonuses(instance['stat_bonuses'])}"
                )
                continue
            item_name = equipped.get(slot_key)
            if item_name and item_name in avatar_gear.AVATAR_GEAR:
                gear = avatar_gear.AVATAR_GEAR[item_name]
                lines.append(f"{emoji} **{label}**: {item_name} (legacy) — {avatar_gear.describe_avatar_stat_bonuses(gear.stat_bonuses)}")
            else:
                lines.append(f"{emoji} **{label}**: *empty*")
        embed.description = "\n".join(lines)
        embed.add_field(name="Avatar Power", value=f"**{status['power']:.1f}**", inline=False)
        embed.set_footer(
            text=f"Selected slot: {avatar_gear.SLOT_LABEL_BY_KEY[self.selected_slot]} — pick a slot, then an item, below. "
            "New gear drops from /rba (commonly) and raid bosses (rarely) once you've reached Nascent Soul."
        )

    def _fill_levelup_embed(self, embed: discord.Embed, status: dict):
        if status["soul"] is None:
            embed.description = "Choose a soul first (Soul tab) — your avatar needs a soul before it can level up."
            return
        level = status["level"]
        embed.description = f"Level **{avatar.level_name(level)}** (Avatar Power **{status['power']:.1f}**)"
        recipe = status["next_recipe"]
        if recipe is None:
            embed.add_field(name="Max Level", value="Your avatar has reached its peak — Level X.", inline=False)
            return
        inventory = self.game.get_inventory(self.user_id)
        lines = [f"**{item}**: {inventory.get(item, 0)}/{qty}" for item, qty in recipe.items()]
        embed.add_field(name=f"Next: Level {avatar.level_name(level + 1)}", value="\n".join(lines), inline=False)
