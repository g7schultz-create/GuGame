import asyncio
import random

import discord

from . import chargen, combat
from .base_view import GameView
from .equipment import EQUIPMENT
from .items import ITEMS
from .ui_utils import render_bar

FLEE_BASE_CHANCE = 0.5
FLEE_CHANCE_PER_SPD_DIFF = 0.02
MIN_FLEE_CHANCE = 0.1
MAX_FLEE_CHANCE = 0.9

GUARD_DAMAGE_REDUCTION = 0.5
POTION_USE_CAP = 3
MAX_LOG_LINES = 4

EMPOWER_QI_COST = 15

# Same AFK safeguard /hunt uses — see hunt.py's HUNT_ROUND_TIMEOUT_SECONDS for the reasoning.
PVP_ROUND_TIMEOUT_SECONDS = 30

# The AI opponent's per-turn action — a plain Attack most of the time ("favoring attacking"
# per the request), otherwise it braces and skips its attack that round entirely (there's no
# earlier player action left to retroactively reduce, so "guard" here just means "whiffs").
OPPONENT_ATTACK_CHANCE = 0.75

STATUS_LABELS = {"fighting": "Fighting", "victory": "Victory!", "defeat": "Defeat", "fled": "Fled"}
STATUS_COLORS = {
    "fighting": discord.Color.dark_gold(),
    "victory": discord.Color.green(),
    "defeat": discord.Color.dark_red(),
    "fled": discord.Color.greyple(),
}


class PvPView(GameView):
    """/pvp: fight an AI-controlled opponent built from another player's stat snapshot —
    either someone who's recently searched for a match themselves (last_pvp_ts within the
    cooldown window — see GameManager.find_pvp_opponent), or a random other confirmed
    character if nobody qualifies. Never a live second player and never anything written
    back to the opponent's own account; only the initiator's outcome is real. Structurally
    this is HuntView with the Monster swapped for a snapshot + simple attack-favoring AI (no
    fixed ability, no item drops — just a nominal spirit-stone reward for winning) — see
    hunt.py for the shared action/AFK-timer design this mirrors."""

    def __init__(self, user_id: int, game, player, display_name: str, avatar_url: str, opponent_name: str, opponent_stats: dict, is_real: bool):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.game = game
        self.player = player
        self.display_name = display_name
        self.avatar_url = avatar_url
        self.opponent_name = opponent_name
        self.opponent_stats = opponent_stats
        self.is_real = is_real

        self.round = 1
        self.opponent_hp = opponent_stats["hp"]
        self.opponent_max_hp = opponent_stats["hp"]
        # Equipped gear's flat "hp"/"qi_stat" stat_bonuses are folded in as a live overlay on
        # top of the persisted (gear-independent) hp/max_hp and battle_qi/qi_stat columns,
        # same as atk/str/def/spd/luck already work — see _persist_hp/_persist_qi for why
        # writes back to the DB subtract them back out again.
        equip_bonuses = self.game.compute_equipment_bonuses(user_id)["stats"]
        self.hp_bonus = equip_bonuses["hp"]
        hp_settled = self.game.db.settle_hp_regen(user_id)
        self.player_hp = hp_settled["hp"] + self.hp_bonus
        self.player_max_hp = hp_settled["max_hp"] + self.hp_bonus
        # It's just for fun — whatever happens to your HP during the duel (damage, lifesteal,
        # potions, ...) gets undone the moment it ends, win or lose. See _restore_starting_hp.
        self.starting_hp = hp_settled["hp"]
        self.qi_bonus = equip_bonuses["qi_stat"]
        settled = self.game.db.settle_battle_qi(user_id)
        self.player_qi = settled["battle_qi"] + self.qi_bonus
        self.player_max_qi = settled["qi_stat"] + self.qi_bonus
        self.qi_empowered = False
        self.log: list = []
        self.status = "fighting"
        self.potions_used = 0
        self.stones_awarded = 0
        self.message: discord.Message = None
        self._round_epoch = 0

        self._build_components()
        self._start_round_timer()

    # -- helpers -----------------------------------------------------------

    def _equipment_bonuses(self) -> dict:
        return self.game.compute_equipment_bonuses(self.user_id)

    def _player_combat_stats(self) -> dict:
        bonuses = self._equipment_bonuses()
        stats_bonus = bonuses["stats"]
        p = self.player
        stats = {
            "atk_stat": p["atk_stat"] + stats_bonus["atk_stat"],
            "str_stat": p["str_stat"] + stats_bonus["str_stat"],
            "def_stat": p["def_stat"] + stats_bonus["def_stat"],
            "spd_stat": p["spd_stat"] + stats_bonus["spd_stat"],
            "luck_stat": p["luck_stat"] + stats_bonus["luck_stat"],
        }
        low_hp_bonus = bonuses.get("low_hp_atk_bonus", 0)
        if low_hp_bonus and 0 < self.player_hp < self.player_max_hp * 0.5:
            stats["str_stat"] += low_hp_bonus
        return stats

    def _equipped_gu(self):
        gu_name = self.game.get_equipped(self.user_id).get("gu_ability")
        return EQUIPMENT.get(gu_name) if gu_name else None

    def _persist_hp(self):
        self.game.db.set_hp(self.user_id, max(1, self.player_hp - self.hp_bonus))

    def _persist_qi(self):
        """Writes self.player_qi back to the DB — minus qi_bonus, mirroring _persist_hp
        (db.set_battle_qi's own clamp is against the un-bonused qi_stat column, so
        persisting the inflated number would just get silently cut back down)."""
        self.game.db.set_battle_qi(self.user_id, max(0.0, self.player_qi - self.qi_bonus))

    def _restore_starting_hp(self):
        """Called the instant the duel ends (win, lose, flee, or timeout) — resets real HP
        back to whatever it was when the duel started, so nothing here has a lasting cost."""
        self.game.db.set_hp(self.user_id, self.starting_hp)

    def _log_line(self, text: str):
        self.log.append(f"Round {self.round}: {text}")
        self.log = self.log[-MAX_LOG_LINES:]

    def _finish_round(self):
        if self.status == "fighting":
            self.round += 1
            self._start_round_timer()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your duel.", ephemeral=True)
            return False
        return True

    async def _refresh_message(self):
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    def _start_round_timer(self):
        self._round_epoch += 1
        asyncio.create_task(self._round_timeout(self._round_epoch))

    async def _round_timeout(self, epoch: int):
        await asyncio.sleep(PVP_ROUND_TIMEOUT_SECONDS)
        if self.status != "fighting" or epoch != self._round_epoch:
            return
        self.qi_empowered = False
        self._log_line("⏱️ You hesitate too long — your body swings on reflex!")

        # _finish_round (and the create_task it can trigger via _start_round_timer) must run
        # on the main thread -- asyncio.create_task requires a running loop in the CURRENT
        # thread, which a asyncio.to_thread worker never has. Only the DB-touching combat
        # resolution itself is offloaded; _finish_round/_build_components stay on the loop.
        await asyncio.to_thread(self._do_attack)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        await self._refresh_message()

    # -- combat resolution ---------------------------------------------------

    def _opponent_turn(self, incoming_reduction: float = 0.0):
        if self.status != "fighting":
            return
        if random.random() >= OPPONENT_ATTACK_CHANCE:
            self._log_line(f"{self.opponent_name} braces warily instead of attacking.")
            return
        # Rockman's "-15% dmg above 50% HP" and Rare Physique's small flat reduction.
        race_physique_reduction = chargen.race_physique_damage_reduction(
            self.player["race"], self.player["physique_tier"], self.player_hp / self.player_max_hp,
        )
        if race_physique_reduction:
            incoming_reduction = 1 - (1 - incoming_reduction) * (1 - race_physique_reduction)
        if incoming_reduction >= 1.0:
            self._log_line(f"You fully block {self.opponent_name}'s attack!")
            return
        bonuses = self._equipment_bonuses()
        result = combat.resolve_attack(
            self.opponent_stats, self._player_combat_stats(),
            incoming_reduction=incoming_reduction, dodge_chance_bonus=bonuses.get("dodge_chance_pct", 0),
        )
        if not result.hit:
            self._log_line(f"{self.opponent_name} attacks but misses!")
        elif result.dodged:
            self._log_line(f"You dodge {self.opponent_name}'s attack!")
        else:
            # No Mythic Physique fatal-hit negation here on purpose: a PvP "death" already
            # costs nothing (see _restore_starting_hp) — spending the once-per-day charge on
            # a duel that was already harmless would just deny it to a hunt/raid that isn't.
            self.player_hp = max(0, self.player_hp - result.damage)
            self._persist_hp()
            crit = " (Critical!)" if result.crit else ""
            self._log_line(f"{self.opponent_name} hits you for {result.damage} damage{crit}.")
        if self.player_hp <= 0:
            self.status = "defeat"
            self.player_hp = 1
            self._restore_starting_hp()
            self._log_line("You are beaten and forced to retreat — it's just a duel, no real harm done.")

    def _do_attack(self, str_multiplier: float = 1.0, label: str = "Attack", guaranteed_hit: bool = False, is_technique: bool = False):
        bonuses = self._equipment_bonuses()
        damage_pct_bonus = (bonuses.get("technique_damage_pct", 0) if is_technique else bonuses.get("physical_damage_pct", 0)) + bonuses.get("total_damage_pct", 0)
        result = combat.resolve_attack(
            self._player_combat_stats(), self.opponent_stats, str_multiplier=str_multiplier, guaranteed_hit=guaranteed_hit,
            crit_chance_bonus=bonuses.get("crit_chance_pct", 0), crit_damage_bonus=bonuses.get("crit_damage_pct", 0),
            lifesteal_percent=bonuses.get("lifesteal_percent", 0), damage_pct_bonus=damage_pct_bonus,
            # Nascent Soul Avatar (see avatar.py, Sword Soul) — passive only here, no Soul
            # Projection button in PvP (out of Phase 2's scope); crit/lifesteal/etc above
            # already silently apply once compute_equipment_bonuses folds the soul in, this
            # is just the one key that needed an explicit new kwarg to keep pace with them.
            armor_penetration_pct=bonuses.get("armor_penetration_pct", 0),
        )
        if not result.hit:
            self._log_line(f"You use {label} but miss!")
        elif result.dodged:
            self._log_line(f"{self.opponent_name} dodges your {label}!")
        else:
            self.opponent_hp = max(0, self.opponent_hp - result.damage)
            crit = " (Critical!)" if result.crit else ""
            heal_text = ""
            if result.heal:
                self.player_hp = min(self.player_max_hp, self.player_hp + result.heal)
                self._persist_hp()
                heal_text = f" You drain {result.heal} HP."
            self._log_line(f"You use {label} for {result.damage} damage{crit}.{heal_text}")
        if self.opponent_hp <= 0:
            self.status = "victory"
            self.stones_awarded = self.game.award_pvp_victory(self.user_id)
            self._restore_starting_hp()
            self._log_line(f"{self.opponent_name} is defeated!")
        else:
            self._opponent_turn()

    # -- action handlers -----------------------------------------------------

    def _consume_empower(self) -> bool:
        used = self.qi_empowered and self.player_qi >= EMPOWER_QI_COST
        if used:
            self.player_qi -= EMPOWER_QI_COST
            self._persist_qi()
        self.qi_empowered = False
        return used

    async def _on_attack(self, interaction: discord.Interaction):
        def _resolve():
            empowered = self._consume_empower()
            if empowered:
                self._log_line("You channel Qi to guarantee your strike!")
            self._do_attack(guaranteed_hit=empowered)

        # _finish_round (and the create_task it can trigger) must run on the main thread, not
        # inside a to_thread worker -- see _round_timeout's comment for why.
        await asyncio.to_thread(_resolve)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_guard(self, interaction: discord.Interaction):
        def _resolve():
            empowered = self._consume_empower()
            if empowered:
                self._log_line("You channel Qi to fully brace against the blow!")
            else:
                self._log_line("You brace for the next blow.")
            self._opponent_turn(incoming_reduction=1.0 if empowered else GUARD_DAMAGE_REDUCTION)

        await asyncio.to_thread(_resolve)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_toggle_empower(self, interaction: discord.Interaction):
        self.qi_empowered = not self.qi_empowered
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_flee(self, interaction: discord.Interaction):
        def _resolve():
            stats = self._player_combat_stats()
            chance = FLEE_BASE_CHANCE + (stats["spd_stat"] - self.opponent_stats["spd_stat"]) * FLEE_CHANCE_PER_SPD_DIFF
            chance = max(MIN_FLEE_CHANCE, min(MAX_FLEE_CHANCE, chance))
            if random.random() < chance:
                self.status = "fled"
                self._restore_starting_hp()
                self._log_line("You break away and escape the duel!")
                return False
            self._log_line("You fail to escape!")
            self._opponent_turn()
            return True

        needs_finish = await asyncio.to_thread(_resolve)
        if needs_finish:
            self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_gu_ability(self, interaction: discord.Interaction):
        gu = await asyncio.to_thread(self._equipped_gu)
        ability = gu.active_ability if gu else None
        if not ability:
            await interaction.response.send_message("You have no active Gu ability equipped.", ephemeral=True)
            return
        if self.player_qi < ability.qi_cost:
            await interaction.response.send_message(f"Not enough Qi to use {ability.name} (needs {ability.qi_cost}).", ephemeral=True)
            return

        def _resolve():
            self.player_qi -= ability.qi_cost
            self._persist_qi()
            self._log_line(f"You channel {ability.name}!")
            self._do_attack(str_multiplier=ability.str_multiplier, label=ability.name, is_technique=True)

        await asyncio.to_thread(_resolve)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_killer_move(self, interaction: discord.Interaction):
        """Additive alongside _on_gu_ability above, not a replacement -- see hunt.py's
        identical twin for the full reasoning."""
        move = await asyncio.to_thread(self.game.get_equipped_killer_move, self.player, "combat")
        if not move:
            await interaction.response.send_message("You have no Killer Move equipped in your Combat slot.", ephemeral=True)
            return
        qi_cost = await asyncio.to_thread(self.game.killer_move_qi_cost, self.player, move)
        if self.player_qi < qi_cost:
            await interaction.response.send_message(f"Not enough Qi to use {move['name']} (needs {qi_cost:,}).", ephemeral=True)
            return

        def _resolve():
            self.player_qi -= qi_cost
            self._persist_qi()
            self._log_line(f"You unleash {move['name']}!")
            if move["kind"] == "damage":
                self._do_attack(str_multiplier=move["effects"]["str_multiplier"], label=move["name"], is_technique=True)
            else:
                self.game.apply_killer_move_buff(self.user_id, self.player, move)
                self._log_line(f"{move['name']} surges through you!")
                self._opponent_turn()

        await asyncio.to_thread(_resolve)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_use_potion(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        item_name = select.values[0]
        if item_name == "none":
            await interaction.response.defer()
            return

        def _resolve():
            ok, message = self.game.use_item(self.user_id, self.display_name, item_name)
            if ok:
                self.potions_used += 1
                fresh = self.game.get_player_stats(self.user_id, self.display_name)
                self.player_hp = min(self.player_max_hp, fresh["hp"] + self.hp_bonus)
                self._log_line(f"You use {item_name} — {message}")
                self._opponent_turn()
            else:
                self._log_line(f"Couldn't use {item_name}: {message}")

        await asyncio.to_thread(_resolve)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if self.status == "fighting":
            self.status = "fled"
            await asyncio.to_thread(self._restore_starting_hp)
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    # -- UI building -----------------------------------------------------

    def _build_components(self):
        self.clear_items()
        active = self.status == "fighting"

        buttons = [
            ("Attack", "⚔️", discord.ButtonStyle.primary, self._on_attack),
            ("Guard", "🛡️", discord.ButtonStyle.secondary, self._on_guard),
            ("Flee", "🏃", discord.ButtonStyle.danger, self._on_flee),
        ]
        for label, emoji, style, callback in buttons:
            button = discord.ui.Button(label=label, emoji=emoji, style=style, row=0, disabled=not active)
            button.callback = callback
            self.add_item(button)

        empower_button = discord.ui.Button(
            label=f"Empower ({EMPOWER_QI_COST})",
            emoji="✨",
            style=discord.ButtonStyle.success if self.qi_empowered else discord.ButtonStyle.secondary,
            row=0,
            disabled=not active or (not self.qi_empowered and self.player_qi < EMPOWER_QI_COST),
        )
        empower_button.callback = self._on_toggle_empower
        self.add_item(empower_button)

        gu = self._equipped_gu()
        if gu and gu.active_ability:
            gu_button = discord.ui.Button(
                label=gu.active_ability.name, emoji="🐛", style=discord.ButtonStyle.primary, row=1,
                disabled=not active or self.player_qi < gu.active_ability.qi_cost,
            )
            gu_button.callback = self._on_gu_ability
            self.add_item(gu_button)

        killer_move = self.game.get_equipped_killer_move(self.player, "combat")
        if killer_move:
            killer_move_button = discord.ui.Button(
                label=killer_move["name"], emoji="🌀", style=discord.ButtonStyle.primary, row=1,
                disabled=not active or self.player_qi < self.game.killer_move_qi_cost(self.player, killer_move),
            )
            killer_move_button.callback = self._on_killer_move
            self.add_item(killer_move_button)

        inventory = self.game.get_inventory(self.user_id)
        usable = [
            item for item in ITEMS.values()
            if item.category in ("Healing", "Pills") and item.use is not None and inventory.get(item.name, 0) > 0
        ]
        potion_options = [
            discord.SelectOption(label=f"{item.name} x{inventory[item.name]}", value=item.name, description=item.description[:100])
            for item in usable
        ]
        cap_reached = self.potions_used >= POTION_USE_CAP
        potion_select = discord.ui.Select(
            placeholder=f"Use potion/pill in battle ({self.potions_used}/{POTION_USE_CAP} used)",
            # Capped at Discord's 25-option limit — see hunt.py's identical potion select.
            options=potion_options[:25] or [discord.SelectOption(label="None available", value="none")],
            disabled=not potion_options or cap_reached or not active,
            row=2,
        )
        potion_select.callback = self._on_use_potion
        self.add_item(potion_select)

    def build_embed(self) -> discord.Embed:
        opponent_pct = int(100 * max(0, self.opponent_hp) / self.opponent_max_hp)
        player_pct = int(100 * max(0, self.player_hp) / self.player_max_hp)
        qi_pct = int(100 * max(0, self.player_qi) / max(1, self.player_max_qi))

        embed = discord.Embed(
            title=f"⚔️ PvP Duel vs {self.opponent_name} • {STATUS_LABELS[self.status]}",
            description=f"⚔️ Round **{self.round}** • {'A real cultivator’s combat data' if self.is_real else 'A conjured clone of a random cultivator'}",
            color=STATUS_COLORS[self.status],
        )
        embed.set_thumbnail(url=self.avatar_url)

        embed.add_field(
            name=f"🗡️ {self.opponent_name}",
            value=(
                f"❤️ HP `{max(0, self.opponent_hp):.0f} / {self.opponent_max_hp:.0f}` • {opponent_pct}%\n"
                f"`{render_bar(self.opponent_hp, self.opponent_max_hp)}`"
            ),
            inline=False,
        )

        empower_note = " • ✨ Empowered (next Attack/Guard)" if self.qi_empowered else ""
        embed.add_field(
            name=f"🧍 {self.display_name}",
            value=(
                f"❤️ HP `{max(0, self.player_hp):.0f} / {self.player_max_hp:.0f}` • {player_pct}%\n"
                f"`{render_bar(self.player_hp, self.player_max_hp)}`\n"
                f"💧 Qi `{max(0, self.player_qi):.0f} / {self.player_max_qi:.0f}` • {qi_pct}%\n"
                f"`{render_bar(self.player_qi, self.player_max_qi)}`\n"
                f"Potions used: {self.potions_used}/{POTION_USE_CAP}{empower_note}"
            ),
            inline=False,
        )

        if self.log:
            embed.add_field(name="📜 Recent Combat", value="\n".join(self.log), inline=False)

        if self.status == "victory":
            embed.add_field(
                name="🎁 Reward",
                value=f"**{self.stones_awarded}** 🪙 spirit stones! Your HP is unaffected — it's just a duel.",
                inline=False,
            )
        elif self.status == "defeat":
            embed.add_field(
                name="💀 Outcome",
                value="You were beaten down and forced to retreat. No reward, but no real losses either — your HP is fully restored, it's just a duel.",
                inline=False,
            )
        elif self.status == "fled":
            embed.add_field(name="🏃 Outcome", value="You fled the duel. No reward, and your HP is unaffected.", inline=False)

        embed.set_footer(
            text=(
                f"Choose an action — go quiet for {PVP_ROUND_TIMEOUT_SECONDS}s and you'll auto-attack on reflex instead."
            )
            if self.status == "fighting" else "This duel has ended."
        )
        return embed
