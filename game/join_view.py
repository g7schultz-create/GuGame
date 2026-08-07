import traceback

import discord

from . import chargen
from .base_view import GameView
from .character_class import CLASSES
from .character_data import PATHS, PHYSIQUE_TIERS, RACES, ROOT_TIERS


class CharacterNameModal(discord.ui.Modal, title="Set Character Name"):
    name_input = discord.ui.TextInput(label="Character Name", max_length=32, min_length=1)

    def __init__(self, view: "JoinView", default: str):
        super().__init__()
        self.view_ref = view
        self.name_input.default = default

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.game.set_character_name(self.view_ref.user_id, self.view_ref.display_name, str(self.name_input.value))
        self.view_ref.refresh()
        await interaction.response.edit_message(embed=self.view_ref.build_embed(), view=self.view_ref)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        # Modal has its own separate error hook from View.on_error (see base_view.py) — this
        # is the one other interactive-component entry point in the codebase, so it gets the
        # same "surface a real message instead of silently hanging" treatment directly here.
        print(f"[modal error] CharacterNameModal raised {type(error).__name__}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        message = f"⚠️ Something went wrong ({type(error).__name__}: {error})."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass


class JoinView(GameView):
    def __init__(self, user_id: int, game, display_name: str, avatar_url: str):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.avatar_url = avatar_url
        self.player = self.game.get_player_stats(user_id, display_name)
        self.base_stats = chargen.roll_base_stats()
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your character setup.", ephemeral=True)
            return False
        return True

    def refresh(self):
        self.player = self.game.get_player_stats(self.user_id, self.display_name)
        self._build_components()

    def _selection_objects(self):
        return (
            chargen.get_race(self.player["race"]),
            chargen.get_root_tier(self.player["root_tier"]),
            chargen.get_physique_tier(self.player["physique_tier"]),
            chargen.get_path(self.player["cultivation_path"]),
        )

    def _build_components(self):
        self.clear_items()
        p = self.player
        confirmed = bool(p["character_confirmed"])

        name_button = discord.ui.Button(label="Set Name", emoji="🖋️", disabled=confirmed)
        name_button.callback = self._on_set_name
        self.add_item(name_button)

        race_options = [
            discord.SelectOption(label=race.name, description=race.tagline[:100], value=race.name, default=race.name == p["race"])
            for race in RACES.values()
        ]
        race_select = discord.ui.Select(placeholder="Choose your race", options=race_options, disabled=confirmed)
        race_select.callback = self._on_select_race
        self.add_item(race_select)

        root_label = f"Reroll Root ({p['root_rerolls_remaining']} left)"
        root_button = discord.ui.Button(label=root_label, emoji="🌱", disabled=confirmed or p["root_rerolls_remaining"] <= 0)
        root_button.callback = self._on_reroll_root
        self.add_item(root_button)

        physique_label = f"Reroll Physique ({p['physique_rerolls_remaining']} left)"
        physique_button = discord.ui.Button(label=physique_label, emoji="💪", disabled=confirmed or p["physique_rerolls_remaining"] <= 0)
        physique_button.callback = self._on_reroll_physique
        self.add_item(physique_button)

        path_options = [
            discord.SelectOption(label=path.name, description=path.tagline[:100], value=path.name, default=path.name == p["cultivation_path"])
            for path in PATHS.values()
        ]
        path_select = discord.ui.Select(placeholder="Choose your cultivation path", options=path_options, disabled=confirmed)
        path_select.callback = self._on_select_path
        self.add_item(path_select)

        class_options = [
            discord.SelectOption(
                label=f"{cls.emoji} {cls.name} ({cls.role})", description=cls.tagline[:100],
                value=cls.name, default=cls.name == p["character_class"],
            )
            for cls in CLASSES.values()
        ]
        class_select = discord.ui.Select(placeholder="Choose your combat class", options=class_options, disabled=confirmed)
        class_select.callback = self._on_select_class
        self.add_item(class_select)

        can_confirm = all([p["race"], p["root_tier"], p["physique_tier"], p["cultivation_path"], p["character_class"]])
        confirm_button = discord.ui.Button(
            label="Confirm" if not confirmed else "Confirmed",
            style=discord.ButtonStyle.success,
            disabled=confirmed or not can_confirm,
        )
        confirm_button.callback = self._on_confirm
        self.add_item(confirm_button)

    async def _on_set_name(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CharacterNameModal(self, self.player["character_name"] or self.display_name))

    async def _on_select_race(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.placeholder == "Choose your race")
        self.game.set_race(self.user_id, self.display_name, select.values[0])
        self.refresh()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_select_path(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.placeholder == "Choose your cultivation path")
        self.game.set_path(self.user_id, self.display_name, select.values[0])
        self.refresh()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_select_class(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.placeholder == "Choose your combat class")
        self.game.set_class(self.user_id, self.display_name, select.values[0])
        self.refresh()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_reroll_root(self, interaction: discord.Interaction):
        self.game.reroll_root(self.user_id, self.display_name)
        self.refresh()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_reroll_physique(self, interaction: discord.Interaction):
        self.game.reroll_physique(self.user_id, self.display_name)
        self.refresh()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_confirm(self, interaction: discord.Interaction):
        self.game.confirm_character(self.user_id, self.display_name, self.base_stats)
        self.refresh()
        for child in self.children:
            child.disabled = True
        embed = self.build_embed()
        embed.add_field(name="✅ Character Confirmed", value="Your starter inventory has been granted. Check `/inventory`!", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    def build_embed(self) -> discord.Embed:
        p = self.player
        race, root_tier, physique_tier, path = self._selection_objects()
        confirmed = bool(p["character_confirmed"])

        embed = discord.Embed(
            title="🧬 Character Setup",
            description=f"{p['character_name'] or self.display_name} • {'✅ Confirmed' if confirmed else '⏳ Needs Confirmation'}",
            color=discord.Color.dark_purple(),
        )
        embed.set_thumbnail(url=self.avatar_url)

        if race:
            embed.add_field(
                name="🩸 Race",
                value=f"**{race.name}** — *{race.tagline}*\n" + "\n".join(race.display_bonuses) + f"\n{race.passive}",
                inline=False,
            )
        else:
            embed.add_field(name="🩸 Race", value="Not chosen yet.", inline=False)

        if root_tier:
            value = f"{root_tier.emoji} **{p['root_name']}** ({root_tier.name}) — {p['root_rerolls_remaining']} rerolls left\n"
            value += "\n".join(root_tier.display_bonuses)
            if root_tier.passive:
                value += f"\nPassive: {root_tier.passive}"
            passive = chargen.unique_passive(ROOT_TIERS, p["root_tier"], p["root_name"])
            if passive:
                value += f"\n✨ {passive}"
            root_spec = chargen.get_root_spec(p["root_name"])
            if root_spec:
                value += f"\n🔹 {root_spec.description}"
            embed.add_field(name="🌱 Root", value=value, inline=False)
        else:
            embed.add_field(name="🌱 Root", value=f"Not rolled yet. {p['root_rerolls_remaining']} rerolls available.", inline=False)

        if physique_tier:
            value = f"{physique_tier.emoji} **{p['physique_name']}** ({physique_tier.name}) — {p['physique_rerolls_remaining']} rerolls left\n"
            value += "\n".join(physique_tier.display_bonuses)
            if physique_tier.passive:
                value += f"\nPassive: {physique_tier.passive}"
            passive = chargen.unique_passive(PHYSIQUE_TIERS, p["physique_tier"], p["physique_name"])
            if passive:
                value += f"\n✨ {passive}"
            physique_spec = chargen.get_physique_spec(p["physique_name"])
            if physique_spec:
                value += f"\n🔹 {physique_spec.description}"
            embed.add_field(name="💪 Physique", value=value, inline=False)
        else:
            embed.add_field(name="💪 Physique", value=f"Not rolled yet. {p['physique_rerolls_remaining']} rerolls available.", inline=False)

        if path:
            embed.add_field(
                name="⚔️ Cultivation Path",
                value=f"**{path.name}** — *{path.tagline}*\n" + "\n".join(path.display_bonuses) + f"\nPassive — {path.passive_name}: {path.passive_text}\nWeakness: {path.weakness}",
                inline=False,
            )
        else:
            embed.add_field(name="⚔️ Cultivation Path", value="Not chosen yet. You may change this freely before confirming.", inline=False)

        character_class = chargen.get_character_class(p["character_class"])
        if character_class:
            embed.add_field(
                name="🎭 Class",
                value=(
                    f"{character_class.emoji} **{character_class.name}** ({character_class.role}) — *{character_class.tagline}*\n"
                    + "\n".join(character_class.display_bonuses)
                    + f"\nPassive — {character_class.passive_name}: {character_class.passive_text}"
                    + f"\nRaid Ability — {character_class.ability_name}: {character_class.ability_text}"
                ),
                inline=False,
            )
        else:
            embed.add_field(name="🎭 Class", value="Not chosen yet. You may change this freely before confirming — it's permanent once you do.", inline=False)

        if confirmed:
            stats = p
        else:
            stats = chargen.compute_final_stats(self.base_stats, race, root_tier, physique_tier, path, character_class)
        embed.add_field(
            name="💎 Foundation Stats",
            value=(
                f"🎯 **ATK** {stats['atk_stat']} ⚔️ **STR** {stats['str_stat']} ❤️ **HP** {stats['hp']}\n"
                f"🏃 **SPD** {stats['spd_stat']} 🍀 **LCK** {stats['luck_stat']} 💧 **QI** {stats['qi_stat']} 🛡️ **DEF** {stats['def_stat']}"
            ),
            inline=False,
        )
        max_rerolls = self.game.db.STARTER_REROLLS
        embed.set_footer(
            text=f"Race chosen directly • Root {p['root_rerolls_remaining']}/{max_rerolls} • "
            f"Physique {p['physique_rerolls_remaining']}/{max_rerolls} • "
            "Confirming locks this character and grants a starter inventory. Out of rerolls? Try /shop."
        )
        return embed
