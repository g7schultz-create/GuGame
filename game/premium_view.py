from collections import Counter

import discord

from . import chargen
from .base_view import GameView
from .character_data import PHYSIQUE_TIERS, RACES, ROOT_TIER_ORDER, ROOT_TIERS
from .shop import _best_roll, _format_current

KIND_LABELS = {"root": ("🌱", "Root"), "physique": ("💪", "Physique"), "race": ("🧬", "Race")}


def _tier_histogram(rolls: list) -> str:
    counts = Counter(tier for tier, _ in rolls)
    return ", ".join(f"{tier} x{counts[tier]}" for tier in ROOT_TIER_ORDER if tier in counts)


def _format_result(label: str, rolls: list, hit_target: bool, ran_out_of_money: bool, target_tier: str) -> str:
    histogram = _tier_histogram(rolls)
    if hit_target:
        return f"🎯 {label}: rolled {len(rolls)}x and hit **{target_tier}+**! {histogram}"
    best = _best_roll(rolls)[0]
    if ran_out_of_money:
        return f"💸 {label}: rolled {len(rolls)}x and ran out of spirit stones without reaching **{target_tier}** — best was **{best}**. {histogram}"
    return (
        f"⏸️ {label}: rolled {len(rolls)}x (hit the per-click safety cap) without reaching **{target_tier}** — "
        f"best was **{best}**. You still have spirit stones left — click Roll again to keep going. {histogram}"
    )


def _format_race(race) -> str:
    if race is None:
        return "Not set."
    value = f"**{race.name}** — _{race.tagline}_\n" + "\n".join(race.display_bonuses)
    if race.passive:
        value += f"\nPassive: {race.passive}"
    return value


class PremiumView(GameView):
    DEFAULT_TARGET_TIER = "Legendary"

    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.last_result: str = None
        self.selected_kind = "root"
        self.target_tier = self.DEFAULT_TARGET_TIER
        # A rolled-but-undecided candidate for whichever of root/physique is currently
        # selected — race has no equivalent (see selected_race below), it's a direct pick
        # with no keep/take step.
        self.pending = None
        self.selected_race: str = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your premium roll session.", ephemeral=True)
            return False
        return True

    def _cost(self) -> int:
        if self.selected_kind == "root":
            return self.game.SHOP_ROOT_REROLL_COST
        if self.selected_kind == "physique":
            return self.game.SHOP_PHYSIQUE_REROLL_COST
        return self.game.PREMIUM_RACE_CHANGE_COST

    def _build_components(self):
        self.clear_items()
        player = self.game.get_player_stats(self.user_id, self.display_name)
        stones = player["spirit_stones"]
        if self.selected_race is None:
            self.selected_race = player["race"]

        kind_select = discord.ui.Select(
            placeholder="Roll Root, Physique, or change Race...",
            options=[
                discord.SelectOption(label=label, emoji=emoji, value=key, default=(key == self.selected_kind))
                for key, (emoji, label) in KIND_LABELS.items()
            ],
            row=0,
        )
        kind_select.callback = self._on_pick_kind
        self.add_item(kind_select)

        if self.selected_kind == "race":
            race_select = discord.ui.Select(
                placeholder="Choose a race...",
                options=[
                    discord.SelectOption(label=race_name, default=(race_name == self.selected_race))
                    for race_name in RACES
                ],
                row=1,
            )
            race_select.callback = self._on_pick_race
            self.add_item(race_select)

            change_button = discord.ui.Button(
                label=f"Change Race to {self.selected_race}", emoji="🧬", style=discord.ButtonStyle.primary,
                disabled=stones < self._cost() or self.selected_race == player["race"], row=2,
            )
            change_button.callback = self._on_change_race
            self.add_item(change_button)
            return

        target_select = discord.ui.Select(
            placeholder=f"Stop rolling at {self.target_tier}+...",
            options=[
                discord.SelectOption(label=tier, value=tier, default=(tier == self.target_tier))
                for tier in ROOT_TIER_ORDER
            ],
            row=1,
        )
        target_select.callback = self._on_pick_target
        self.add_item(target_select)

        locked = self.pending is not None
        emoji, label = KIND_LABELS[self.selected_kind]
        roll_button = discord.ui.Button(
            label=f"Roll Until Broke or {self.target_tier}+", emoji="🎰", style=discord.ButtonStyle.primary,
            disabled=stones < self._cost() or locked, row=2,
        )
        roll_button.callback = self._on_roll
        self.add_item(roll_button)

        if self.pending:
            _, name = self.pending
            keep_button = discord.ui.Button(label=f"Keep Old {label}", emoji="↩️", style=discord.ButtonStyle.secondary, row=2)
            keep_button.callback = self._on_keep
            self.add_item(keep_button)
            take_button = discord.ui.Button(label=f"Take New {label} ({name})", emoji="✅", style=discord.ButtonStyle.success, row=2)
            take_button.callback = self._on_take
            self.add_item(take_button)

    async def _on_pick_kind(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        self.selected_kind = select.values[0]
        self.pending = None
        self.last_result = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_pick_target(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        self.target_tier = select.values[0]
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_pick_race(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        self.selected_race = select.values[0]
        self.last_result = None
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_change_race(self, interaction: discord.Interaction):
        ok, message = self.game.change_race(self.user_id, self.display_name, self.selected_race)
        self.last_result = message
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_roll(self, interaction: discord.Interaction):
        # A full "until broke" run can be hundreds of DB round-trips — defer first so we
        # have up to 15 minutes to finish instead of Discord's normal 3-second ack window.
        await interaction.response.defer()
        buy_fn = self.game.premium_root_reroll if self.selected_kind == "root" else self.game.premium_physique_reroll
        rolls, hit_target, ran_out_of_money = buy_fn(self.user_id, self.display_name, self.target_tier)
        emoji, label = KIND_LABELS[self.selected_kind]
        if not rolls:
            self.last_result = "Not enough spirit stones to roll even once."
        else:
            self.pending = _best_roll(rolls)
            self.last_result = _format_result(f"{emoji} {label}", rolls, hit_target, ran_out_of_money, self.target_tier)
        self._build_components()
        await interaction.edit_original_response(embed=self.build_embed(), view=self)

    async def _on_keep(self, interaction: discord.Interaction):
        self.pending = None
        self.last_result = "Kept what you had."
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_take(self, interaction: discord.Interaction):
        tier, name = self.pending
        if self.selected_kind == "root":
            self.game.db.set_root(self.user_id, tier, name)
        else:
            self.game.db.set_physique(self.user_id, tier, name)
        self.pending = None
        self.last_result = f"Took the new one: **{name}** ({tier})!"
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def _race_embed_fields(self, embed: discord.Embed, player: dict):
        embed.add_field(name="🧬 Current Race", value=_format_race(chargen.get_race(player["race"])), inline=False)
        if self.selected_race and self.selected_race != player["race"]:
            embed.add_field(name="🆕 Candidate Race", value=_format_race(chargen.get_race(self.selected_race)), inline=False)
        embed.set_footer(
            text=f"Changing race costs {self.game.PREMIUM_RACE_CHANGE_COST} spirit stones and takes effect immediately — "
                 "it doesn't retroactively change stats your old race already baked in at character creation, only "
                 "ongoing bonuses (cultivation speed, breakthrough chance, etc.) and race-specific passives."
        )

    def build_embed(self) -> discord.Embed:
        player = self.game.get_player_stats(self.user_id, self.display_name)

        embed = discord.Embed(title="💎 Premium", color=discord.Color.purple())
        embed.add_field(name="🪙 Spirit Stones", value=f"{player['spirit_stones']:,}", inline=False)

        if self.selected_kind == "race":
            embed.description = "Pick a race from the dropdown, then **Change Race** to switch to it immediately — no roll, no luck involved."
            self._race_embed_fields(embed, player)
            if self.last_result:
                embed.add_field(name="Result", value=self.last_result[:1024], inline=False)
            return embed

        emoji, label = KIND_LABELS[self.selected_kind]
        catalog = ROOT_TIERS if self.selected_kind == "root" else PHYSIQUE_TIERS
        current_tier = player["root_tier"] if self.selected_kind == "root" else player["physique_tier"]
        current_name = player["root_name"] if self.selected_kind == "root" else player["physique_name"]

        embed.description = (
            f"Pick Root or Physique and a target tier, then **Roll Until Broke or Target** keeps rerolling "
            f"on its own — one spirit stone at a time — stopping the instant it hits your target (or anything "
            f"rarer), or the moment you can't afford another roll. Capped at "
            f"{self.game.PREMIUM_MAX_ROLLS_PER_CLICK} rolls per click as a safety valve — if it stops early "
            "and you've still got stones, just click Roll again."
        )
        embed.add_field(name=f"{emoji} Current {label}", value=_format_current(current_tier, current_name, catalog), inline=False)
        if self.pending:
            tier, name = self.pending
            embed.add_field(name=f"🆕 Candidate {label}", value=_format_current(tier, name, catalog), inline=False)
        if self.last_result:
            embed.add_field(name="Result", value=self.last_result[:1024], inline=False)
        return embed
