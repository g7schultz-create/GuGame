"""
WorldBossView -- /raidboss_attack's interactive session. Turns what used to be one instant,
all-5-swings-at-once flurry into a real round-by-round "click Attack, watch the HP bar move"
experience matching /raid's own feel, per explicit user request ("make it so the raid boss
command actually lets the player attack like a raid").

Deliberately does NOT give the boss a retaliation/incoming-damage mechanic, per this same
user's explicit follow-up choice when asked: every cultivation realm should still be able to
safely tap the World Boss with zero HP risk, same as the original design -- this view is
about the INTERACTIVE FEEL (buttons, live HP bar, a session you play through), not about
adding danger. That's also why there's no Guard/potion row here (see HuntView/BattlefieldView)
-- those exist to mitigate incoming damage, which never happens against this boss.
"""

import discord

from . import world_boss
from .base_view import GameView
from .ui_utils import render_bar

MAX_LOG_LINES = 5


class WorldBossView(GameView):
    def __init__(self, user_id: int, game, display_name: str, avatar_url: str, boss: dict, on_defeat=None):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.game = game
        self.display_name = display_name
        self.avatar_url = avatar_url
        self.boss_instance_id = boss["boss_instance_id"]
        self.roster = world_boss.WORLD_BOSSES[boss["boss_key"]]
        self.boss_hp = boss["current_hp"]
        self.boss_max_hp = boss["max_hp"]
        # Optional async callback(end_summary) -- lets the cog still broadcast a server-wide
        # defeat announcement even though the defeat itself can now happen mid-interaction,
        # deep inside a button click, not at the top-level command handler anymore.
        self.on_defeat = on_defeat

        self.swings_used = 0
        self.max_swings = world_boss.WORLD_BOSS_ATTACKS_PER_COOLDOWN
        self.session_damage = 0
        self.log: list = []
        self.status = "fighting"  # "fighting" | "left" | "defeated" | "boss_gone"
        self.end_summary = None
        self.message: discord.Message = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your fight.", ephemeral=True)
            return False
        return True

    def _log_line(self, text: str):
        self.log.append(text)
        self.log = self.log[-MAX_LOG_LINES:]

    def _build_components(self):
        self.clear_items()
        active = self.status == "fighting"

        attack_button = discord.ui.Button(
            label=f"Attack ({self.swings_used}/{self.max_swings})", emoji="⚔️",
            style=discord.ButtonStyle.primary, disabled=not active, row=0,
        )
        attack_button.callback = self._on_attack
        self.add_item(attack_button)

        leave_button = discord.ui.Button(label="Leave", emoji="🚪", style=discord.ButtonStyle.secondary, disabled=not active, row=0)
        leave_button.callback = self._on_leave
        self.add_item(leave_button)

    async def _on_attack(self, interaction: discord.Interaction):
        result = self.game.resolve_world_boss_swing(self.user_id, self.display_name, self.boss_instance_id)
        if not result["ok"]:
            self.status = "boss_gone"
            self._log_line("💨 The World Boss is already gone — someone else must have finished it (or it expired).")
            self._build_components()
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
            return

        self.swings_used += 1
        self.boss_hp = result["boss_hp_remaining"]
        self.boss_max_hp = result["boss_max_hp"]
        swing_total = result["damage"] + result["bonus_damage"]
        self.session_damage += swing_total

        if not result["hit"]:
            self._log_line("❌ You strike, but miss entirely!")
        elif result["dodged"]:
            self._log_line(f"💨 **{self.roster['name']}** shrugs off the blow before it lands!")
        else:
            crit = " (Critical!)" if result["crit"] else ""
            line = f"⚔️ **{result['damage']:,}** damage{crit}!"
            if result["bonus_damage"]:
                line += f" 🗡️ Flying Sword Gu strikes again for **{result['bonus_damage']:,}**!"
            self._log_line(line)

        if result["defeated"]:
            self.status = "defeated"
            self.end_summary = result["end_summary"]
        elif self.swings_used >= self.max_swings:
            self.status = "left"

        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)
        if result["defeated"] and self.on_defeat:
            await self.on_defeat(self.end_summary)

    async def _on_leave(self, interaction: discord.Interaction):
        self.status = "left"
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self):
        if self.status == "fighting":
            self.status = "left"
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(embed=self.build_embed(), view=self)
            except discord.HTTPException:
                pass

    def build_embed(self) -> discord.Embed:
        pct = 100 * max(0, self.boss_hp) / self.boss_max_hp
        title_status = {
            "fighting": "Fighting", "left": "Session Complete",
            "defeated": "Defeated!", "boss_gone": "Boss Already Gone",
        }[self.status]
        color = {
            "fighting": discord.Color.dark_gold(), "left": discord.Color.dark_teal(),
            "defeated": discord.Color.gold(), "boss_gone": discord.Color.greyple(),
        }[self.status]
        embed = discord.Embed(
            title=f"{self.roster['emoji']} {self.roster['name']} — {title_status}",
            description=f"*{self.roster['theme']}*\n_{self.roster['description']}_",
            color=color,
        )
        embed.set_thumbnail(url=self.avatar_url)
        embed.add_field(
            name="❤️ World Boss HP",
            value=f"`{max(0, self.boss_hp):,} / {self.boss_max_hp:,}` ({pct:.2f}%)\n`{render_bar(self.boss_hp, self.boss_max_hp)}`",
            inline=False,
        )
        embed.add_field(name="🗡️ Your Session Damage", value=f"{self.session_damage:,} ({self.swings_used}/{self.max_swings} strikes used)", inline=True)
        if self.log:
            embed.add_field(name="📜 Recent Strikes", value="\n".join(self.log), inline=False)

        if self.status == "defeated" and self.end_summary:
            s = self.end_summary
            lines = [f"**{s['total_damage']:,}** total damage from **{len(s['contributors'])}** cultivator(s)."]
            for winner in s["lottery_winners"]:
                lines.append(f"🎁 Lottery drop: **{winner['name']}** wins {winner['reward_text']}!")
            embed.add_field(name="🎉 The World Boss Has Fallen!", value="\n".join(lines), inline=False)

        embed.set_footer(text="Next attack session available after the cooldown — check /raidboss.")
        return embed
