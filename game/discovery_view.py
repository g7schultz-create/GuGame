import asyncio
import discord

from .base_view import GameView
from .battlefield_view import BattlefieldView
from .region_dream_realm_view import RegionDreamRealmView

DISCOVERY_TYPE_EMOJI = {"inheritance": "🏛️", "secret_realm": "🌀", "dream_realm": "💤"}
DISCOVERY_TYPE_LABEL = {"inheritance": "Inheritance", "secret_realm": "Secret Realm", "dream_realm": "Dream Realm"}
REWARD_KIND_EMOJI = {"stones": "🪙", "item": "📦", "pages": "📜", "manual": "📖", "clue": "🗝️", "insight": "✨"}


def build_discovery_entry_view(user_id: int, game, display_name: str, avatar_url: str, result: dict):
    """Given an ok=True result from GameManager.enter_discovery, builds whichever View class
    matches result['kind'] (see GameManager.DISCOVERY_ENTRY_KIND) — shared by /discovery's own
    command handler and SearchView's "Enter Discovery" button so the two entry points can
    never drift apart on which view a given kind gets."""
    if result["kind"] == "battlefield":
        player = game.get_player_stats(user_id, display_name)
        return BattlefieldView(user_id, game, player, display_name, avatar_url, result["discovery"])
    if result["kind"] == "stat_check":
        return RegionDreamRealmView(user_id, game, display_name, result["discovery"])
    return DiscoveryView(user_id, game, display_name, result["discovery"], result["total_steps"])


class AbandonDiscoveryView(GameView):
    """Self-service escape hatch attached to /search's "you already have an active discovery"
    and /discovery's "already inside it somewhere else" refusals -- both exist because
    active_discovery_id/enter_discovery's own already-entered check has no dependency on any
    specific message still being reachable, so a player whose original discovery message
    scrolled away, got deleted, or the bot restarted before Back to Search/finishing/timing
    out could clear it would otherwise be stuck with no way to act (discovery has no stale-
    flag self-heal the way /hunt and /raid's flags do -- see reopen_discovery's own docstring
    for why a bare expiry check isn't safe here once a discovery is "entered")."""

    def __init__(self, user_id: int, game, discovery_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.game = game
        self.discovery_id = discovery_id
        button = discord.ui.Button(label="Abandon Stuck Discovery", emoji="🗑️", style=discord.ButtonStyle.danger)
        button.callback = self._on_abandon
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your discovery to clear.", ephemeral=True)
            return False
        return True

    async def _on_abandon(self, interaction: discord.Interaction):
        await asyncio.to_thread(self.game.abandon_discovery, self.user_id, self.discovery_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="🗑️ Cleared — you can `/search` for a new one now.", view=self)


class DiscoveryView(GameView):
    def __init__(self, user_id: int, game, display_name: str, discovery: dict, total_steps: int):
        super().__init__(timeout=600)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.discovery = discovery
        self.total_steps = total_steps
        # Resumes from wherever this discovery's steps_completed column says it left off
        # (defaults to 0 for a freshly-entered discovery) rather than always starting at 0 --
        # otherwise re-entering a still-open discovery (e.g. via SearchView's Back to Search
        # -> Enter Discovery) would spin up a fresh view that replays already-rewarded steps.
        self.step_index = discovery.get("steps_completed", 0)
        self.log: list = []
        self.finished = False
        self.abandoned = False
        self.message: discord.Message = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/discovery` yourself to enter your own find.", ephemeral=True)
            return False
        return True

    def _build_components(self):
        self.clear_items()
        active = not self.finished and not self.abandoned

        continue_button = discord.ui.Button(label="Continue", emoji="➡️", style=discord.ButtonStyle.primary, row=0, disabled=not active)
        continue_button.callback = self._on_continue
        self.add_item(continue_button)

        abandon_button = discord.ui.Button(label="Leave", emoji="🚪", style=discord.ButtonStyle.secondary, row=0, disabled=not active)
        abandon_button.callback = self._on_abandon
        self.add_item(abandon_button)

        back_button = discord.ui.Button(label="Back to Search", emoji="🔙", style=discord.ButtonStyle.secondary, row=0)
        back_button.callback = self._on_back_to_search
        self.add_item(back_button)

    async def _on_continue(self, interaction: discord.Interaction):
        # Defense in depth against a duplicate/stale click getting through anyway (e.g. the
        # very "Unknown interaction" scenario the defer() below exists to prevent in the
        # first place, if it still somehow slips past) -- without this, a second resolve on
        # an already-finished discovery would push step_index past total_steps - 1, and since
        # resolve_discovery_step's is_final check used to be an exact "step_index ==
        # total_steps - 1", once step_index overshoots that value it can never be true again,
        # permanently trapping the discovery in an unfinishable loop (observed live: "Step
        # 51/3" and climbing). manager.py's is_final check is now ">=" as a second, independent
        # safety net, but this guard is the cheaper fix -- never even attempt the resolve.
        if self.finished or self.abandoned:
            await interaction.response.defer()
            return
        # resolve_discovery_step does real DB work (reward rolls, an accessory/artifact roll,
        # and on the final step an EXTRA bonus reward roll) that can run past Discord's 3-second
        # ack window under load -- defer first so a slow step gets up to 15 minutes instead of
        # failing with "Unknown interaction" and leaving this same message's Continue button
        # looking clickable even though the step already resolved server-side (same fix as
        # alchemy_view.py's Make All / InventoryView's Use All).
        await interaction.response.defer()
        result = await asyncio.to_thread(
            self.game.resolve_discovery_step, self.user_id, self.display_name, self.discovery, self.step_index, self.total_steps,
        )
        emoji = REWARD_KIND_EMOJI.get(result["reward"]["kind"], "🎁")
        self.log.append(f"**{result['name']}** — {emoji} {result['reward_text']}")
        if result.get("bonus_reward_text"):
            self.log.append(f"🎁 Bonus: {result['bonus_reward_text']}")
        self.step_index += 1
        if result["is_final"]:
            await asyncio.to_thread(self.game.finish_discovery, self.user_id, self.discovery["discovery_id"])
            self.finished = True
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.edit_original_response(embed=embed, view=self)

    async def _on_abandon(self, interaction: discord.Interaction):
        if self.finished or self.abandoned:
            await interaction.response.defer()
            return
        await asyncio.to_thread(self.game.abandon_discovery, self.user_id, self.discovery["discovery_id"])
        self.abandoned = True
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_back_to_search(self, interaction: discord.Interaction):
        """Returns to the Search hub on this same message without abandoning or finishing
        anything already in progress — if this discovery is still active, its own Enter
        Discovery button on the Search screen will resume it. self.stop() disarms this
        view's on_timeout so it can't later clobber whatever message content replaces it.
        reopen_discovery resets status back to re-enterable -- enter_discovery refuses a
        SECOND entry while status is "entered" (closes the exploit where several /search
        messages all show the same pending discovery and each independently spawn a fresh,
        parallel play-through), so without this, backing out here would permanently lock the
        player out of their own still-open discovery."""
        from .search_view import SearchView  # local import: search_view imports this module
        self.stop()
        await asyncio.to_thread(self.game.reopen_discovery, self.discovery["discovery_id"])
        new_view = SearchView( self.user_id, self.game, self.display_name)
        embed = await asyncio.to_thread(new_view.build_embed)
        await interaction.response.edit_message(embed=embed, view=new_view)
        new_view.message = await interaction.original_response()

    async def on_timeout(self):
        if not self.finished and not self.abandoned:
            await asyncio.to_thread(self.game.abandon_discovery, self.user_id, self.discovery["discovery_id"])
            self.abandoned = True
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    def build_embed(self) -> discord.Embed:
        d = self.discovery
        emoji = DISCOVERY_TYPE_EMOJI.get(d["type"], "❓")
        label = DISCOVERY_TYPE_LABEL.get(d["type"], d["type"])
        if self.finished:
            status_text = "Complete!"
            color = discord.Color.green()
        elif self.abandoned:
            status_text = "Left Early"
            color = discord.Color.greyple()
        else:
            status_text = f"Step {self.step_index + 1}/{self.total_steps}"
            color = discord.Color.dark_gold()

        embed = discord.Embed(
            title=f"{emoji} {d['theme']} • {label} • {status_text}",
            description=f"Rank **{d['rank']}** • Difficulty **{d['difficulty']}**",
            color=color,
        )
        if self.log:
            embed.add_field(name="📜 Discoveries So Far", value="\n".join(self.log)[:1024], inline=False)
        if self.finished:
            embed.set_footer(text="This discovery is complete — run /search to find another.")
        elif self.abandoned:
            embed.set_footer(text="You left the rest behind, but kept what you already found.")
        elif self.step_index > 0 and not self.log:
            embed.set_footer(text=f"Resumed at step {self.step_index + 1} — earlier rewards were already banked. Continue to press deeper, or Leave to keep what you've found so far.")
        else:
            embed.set_footer(text="Continue to press deeper, or Leave to keep what you've found so far.")
        return embed
