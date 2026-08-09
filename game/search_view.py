import asyncio
import discord

from . import search_data
from .base_view import GameView
from .discovery_view import build_discovery_entry_view
from .ui_utils import format_duration

RESULT_EMOJI = {
    "nothing": "🌫️", "minor_find": "🪨", "encounter": "⚔️", "clue": "🧭",
    "clue_completed": "🗺️", "inheritance": "🏛️", "secret_realm": "🌀", "dream_realm": "💤",
}
DISCOVERY_TYPE_EMOJI = {
    "inheritance": "🏛️", "secret_realm": "🌀", "dream_realm": "💤",
    # /region-triggered discoveries (see world_regions.py) can also end up shown here as
    # someone's "Active Discovery" even though /search itself never rolls these two types.
    "battlefield": "⚔️", "region_dream_realm": "💤",
}


def _format_result_text(out: dict) -> str:
    result = out["result"]
    if result == "nothing":
        return "🌫️ Nothing much out there this time — the region feels quiet."
    if result == "minor_find":
        return f"🪨 A minor find: {out['reward_text']}."
    if result == "encounter":
        return f"⚔️ An encounter turns up loot: {out['reward_text']}."
    if result == "clue":
        return f"🧭 A clue fragment toward **{out['theme']}** ({out['fragments']}/{out['fragments_required']})."
    if result == "clue_completed":
        emoji = DISCOVERY_TYPE_EMOJI[out["discovery_type"]]
        return f"🗺️ Your clues finally point somewhere real — {emoji} **{out['theme']}** discovered! Click Enter Discovery below to dive in."
    if result in DISCOVERY_TYPE_EMOJI:
        emoji = DISCOVERY_TYPE_EMOJI[result]
        return f"{emoji} Discovered **{out['theme']['name']}** (Rank {out['rank']}, {out['difficulty']})! Click Enter Discovery below to dive in."
    return "Something happened."


class SearchView(GameView):
    def __init__(self, user_id: int, game, display_name: str):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        status = self.game.get_search_status(user_id, display_name)
        self.selected_region = status["available_regions"][-1]
        self.last_result: str = None
        # Discovering something special makes the "Active Discovery" field show the exact
        # same news as the "Result" field would — this suppresses the redundant Result field
        # for just that case, see _on_search.
        self.last_result_is_discovery = False
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/search` yourself to search on your own charges.", ephemeral=True)
            return False
        return True

    def _status(self) -> dict:
        return self.game.get_search_status(self.user_id, self.display_name)

    def _build_components(self):
        self.clear_items()
        status = self._status()
        if self.selected_region not in status["available_regions"]:
            self.selected_region = status["available_regions"][-1]
        has_active = status["active_discovery"] is not None

        region_select = discord.ui.Select(
            placeholder=f"Region: {self.selected_region}",
            options=[
                discord.SelectOption(label=region, value=region, default=(region == self.selected_region))
                for region in status["available_regions"]
            ],
            row=0,
        )
        region_select.callback = self._on_pick_region
        self.add_item(region_select)

        focus_select = discord.ui.Select(
            placeholder=f"Focus: {status['focus']}",
            options=[
                discord.SelectOption(label=focus, value=focus, default=(focus == status["focus"]))
                for focus in search_data.SEARCH_FOCUS_OPTIONS
            ],
            row=1,
        )
        focus_select.callback = self._on_pick_focus
        self.add_item(focus_select)

        search_button = discord.ui.Button(
            label=f"Search ({status['charges']}/{status['max_charges']} charges)", emoji="🔍",
            style=discord.ButtonStyle.primary, row=2, disabled=has_active or status["charges"] < 1,
        )
        search_button.callback = self._on_search
        self.add_item(search_button)

        if has_active:
            enter_button = discord.ui.Button(label="Enter Discovery", emoji="🚪", style=discord.ButtonStyle.success, row=2)
            enter_button.callback = self._on_enter_discovery
            self.add_item(enter_button)

    async def _on_pick_region(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 0)
        self.selected_region = select.values[0]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_pick_focus(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1)
        await asyncio.to_thread(self.game.set_search_focus, self.user_id, self.display_name, select.values[0])
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_search(self, interaction: discord.Interaction):
        out = await asyncio.to_thread(self.game.run_search, self.user_id, self.display_name, self.selected_region)
        if not out["ok"]:
            if out["reason"] == "active_discovery":
                await interaction.response.send_message("You already have a discovery waiting — use `/discovery` to enter or abandon it first.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Out of search charges — next one in {format_duration(out['seconds_to_next_charge'])}.", ephemeral=True)
            return
        self.last_result = _format_result_text(out)
        self.last_result_is_discovery = out["result"] in (search_data.SPECIAL_RESULTS | {"clue_completed"})
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_enter_discovery(self, interaction: discord.Interaction):
        """Hands this same message straight off to whichever View the active discovery needs
        (DiscoveryView/BattlefieldView/RegionDreamRealmView — see build_discovery_entry_view)
        instead of making the player run a separate /discovery command for a brand-new
        message — the whole point of merging the two."""
        result = await asyncio.to_thread(self.game.enter_discovery, self.user_id, self.display_name)
        if not result["ok"]:
            if result["reason"] == "expired":
                self.last_result = "That discovery expired before you got to it — Search again to find another."
            elif result["reason"] == "already_entered":
                self.last_result = "You're already inside that discovery somewhere else — finish or abandon it there first."
            else:
                self.last_result = "You don't have an active discovery."
            self.last_result_is_discovery = False
            await asyncio.to_thread(self._build_components)
            embed = await asyncio.to_thread(self.build_embed)
            await interaction.response.edit_message(embed=embed, view=self)
            return
        # Constructed directly, NOT via asyncio.to_thread -- can return a BattlefieldView,
        # whose __init__ calls asyncio.create_task (see cog.py's /discovery command for the
        # full reasoning -- both entry points share this same helper).
        new_view = build_discovery_entry_view(self.user_id, self.game, self.display_name, interaction.user.display_avatar.url, result)
        embed = await asyncio.to_thread(new_view.build_embed)
        await interaction.response.edit_message(embed=embed, view=new_view)
        new_view.message = await interaction.original_response()

    def build_embed(self) -> discord.Embed:
        status = self._status()
        embed = discord.Embed(title="🔍 Search", color=discord.Color.dark_teal())
        embed.description = (
            f"🪙 Charges: **{status['charges']}/{status['max_charges']}**"
            + (f" — next in {format_duration(status['seconds_to_next_charge'])}" if status["charges"] < status["max_charges"] else "")
            + f"\n📈 Discovery momentum: **{status['momentum']}**"
            f" (guaranteed clue/encounter at {search_data.MOMENTUM_CLUE_THRESHOLD}, guaranteed special location at {search_data.MOMENTUM_SPECIAL_THRESHOLD})"
        )
        has_active = status["active_discovery"] is not None
        if has_active:
            d = status["active_discovery"]
            emoji = DISCOVERY_TYPE_EMOJI.get(d["type"], "❓")
            embed.add_field(
                name="Active Discovery",
                value=f"{emoji} **{d['theme']}** (Rank {d['rank']}, {d['difficulty']}) — click Enter Discovery below (Search is on hold until you resolve or leave it).",
                inline=False,
            )
        # Skip the Result field when it would just repeat the Active Discovery field above.
        if self.last_result and not (has_active and self.last_result_is_discovery):
            embed.add_field(name="Result", value=self.last_result, inline=False)
        embed.set_footer(text="Pick a region and focus, then Search. Focus nudges the odds toward a category but never guarantees it.")
        return embed
