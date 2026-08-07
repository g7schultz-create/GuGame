"""
BattlefieldView -- the "battlefield" discovery type found via /region actions (see
GameManager.maybe_trigger_region_discovery). "Multiple waves of enemies getting harder and
harder till the cultivator is defeated. Rewards are determined by how many rounds the
cultivator completed."

Deliberately a trimmed-down HuntView (see hunt.py): Attack/Guard/Empower/Flee/Potion/Class
Ability only -- no Gu ability button or per-root/physique trait hooks, an honest scope-down
to keep a genuinely new combat view bounded, matching this session's "don't fake mechanics,
scope down and say so" pattern. Flee doubles as "bank what you've earned so far" -- both
flee and defeat pay out resolve_battlefield_final_reward scaled by however many waves were
actually cleared.
"""

import asyncio
import dataclasses
import random

import discord

from . import avatar, canon_gu, chargen, combat, equipment, realms
from .base_view import GameView
from .items import ITEMS
from .monsters import MONSTERS, hunt_monster_name_for_realm, roll_loot
from .raid import (
    FREEZE_PROC_CHANCE,
    FREEZE_STR_MULTIPLIER,
    INSPIRE_DEF_BONUS_PCT,
    INSPIRE_DURATION_ROUNDS,
    INSPIRE_STR_BONUS_PCT,
)
from .raid import DEFEND_ALLY_DAMAGE_REDUCTION as _BRACE_EXTRA_REDUCTION
from .ui_utils import render_bar

GUARD_DAMAGE_REDUCTION = 0.5
POTION_USE_CAP = 5  # a longer fight than a normal hunt, so a slightly higher cap
MAX_LOG_LINES = 4
EMPOWER_QI_COST = 15
ROUND_TIMEOUT_SECONDS = 30

# Class Ability (see character_class.py / HuntView._on_class_ability, which this mirrors):
#   Tank's Defend Ally    -> Brace: no ally around to redirect hits onto in a solo fight, so
#                            instead brace with the same toughness bonus stacked on a normal Guard.
#   Support's Inspire     -> buffs your own STR/DEF for a few rounds (still costs your attack
#                            that round, same as in a raid).
#   Frostbinder's Freeze  -> a weaker attack with a chance to freeze the monster, making it
#                            skip its next attack.
# Reuses raid.py's own tuning constants directly rather than duplicating magic numbers, same
# as hunt.py's identical comment/derivation.
BRACE_DAMAGE_REDUCTION = 1 - (1 - GUARD_DAMAGE_REDUCTION) * (1 - _BRACE_EXTRA_REDUCTION)

# +stat% per wave past the first -- wave 1 is a normal encounter for this discovery's rank,
# wave 2 is +15%, wave 3 is +30%, and so on, "getting harder and harder."
WAVE_STAT_MULTIPLIER_PER_WAVE = 0.15

STATUS_LABELS = {"fighting": "Fighting", "victory": "Fighting", "defeat": "Defeated", "fled": "Withdrew"}
STATUS_COLORS = {
    "fighting": discord.Color.dark_gold(),
    "defeat": discord.Color.dark_red(),
    "fled": discord.Color.greyple(),
}


class BattlefieldView(GameView):
    def __init__(self, user_id: int, game, player, display_name: str, avatar_url: str, discovery: dict):
        super().__init__(timeout=900)
        self.user_id = user_id
        self.game = game
        self.player = player
        self.display_name = display_name
        self.avatar_url = avatar_url
        self.discovery = discovery
        self.great_realm_index = max(0, min(len(realms.GREAT_REALMS) - 1, discovery["rank"] - 1))
        self.rng = random.Random(discovery["seed"])

        self.wave = 1
        self.monster = self._roll_wave_monster()
        self.round = 1
        self.monster_hp = self.monster.hp
        self.monster_max_hp = self.monster.hp
        # Equipped gear's flat "hp"/"qi_stat" stat_bonuses are folded in as a live overlay on
        # top of the persisted (gear-independent) hp/max_hp and battle_qi/qi_stat columns —
        # see _persist_hp/_persist_qi for why writes back to the DB subtract them back out.
        equip_bonuses = self.game.compute_equipment_bonuses(user_id)["stats"]
        self.hp_bonus = equip_bonuses["hp"]
        hp_settled = self.game.db.settle_hp_regen(user_id)
        self.player_hp = hp_settled["hp"] + self.hp_bonus
        self.player_max_hp = hp_settled["max_hp"] + self.hp_bonus
        self.qi_bonus = equip_bonuses["qi_stat"]
        settled = self.game.db.settle_battle_qi(user_id)
        self.player_qi = settled["battle_qi"] + self.qi_bonus
        self.player_max_qi = settled["qi_stat"] + self.qi_bonus
        self.qi_empowered = False
        self.qi_lost_on_death = 0.0
        # Class Ability state (see BRACE_DAMAGE_REDUCTION comment above): Support's Inspire
        # buff duration, and whether the monster is currently frozen from Frostbinder's Freeze.
        self.inspire_rounds_remaining = 0
        self.monster_frozen_rounds = 0
        # Nascent Soul Avatar's Soul Projection (see avatar.py) — independent of class,
        # gated on having a chosen avatar soul rather than a character_class.
        self.soul_projection_rounds_remaining = 0

        self.log: list = []
        self.status = "fighting"
        self.potions_used = 0
        self.wave_log: list = []
        self.final_reward_text = None
        self.message: discord.Message = None
        self._round_epoch = 0

        self.game.apply_encounter_start_bonuses(user_id, display_name)
        self._build_components()
        self._start_round_timer()

    # -- wave setup -----------------------------------------------------------

    def _roll_wave_monster(self):
        name = hunt_monster_name_for_realm(self.great_realm_index)
        base = MONSTERS[name]
        multiplier = 1.0 + WAVE_STAT_MULTIPLIER_PER_WAVE * (self.wave - 1)
        if multiplier == 1.0:
            return base
        return dataclasses.replace(
            base,
            hp=max(1, round(base.hp * multiplier)), atk_stat=max(1, round(base.atk_stat * multiplier)),
            str_stat=max(1, round(base.str_stat * multiplier)), def_stat=max(1, round(base.def_stat * multiplier)),
            spd_stat=max(1, round(base.spd_stat * multiplier)),
        )

    @property
    def waves_cleared(self) -> int:
        return self.wave - 1

    # -- helpers (mirrors hunt.py's own HuntView) ------------------------------

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
        if self.inspire_rounds_remaining > 0:
            stats["str_stat"] = round(stats["str_stat"] * (1 + INSPIRE_STR_BONUS_PCT))
            stats["def_stat"] = round(stats["def_stat"] * (1 + INSPIRE_DEF_BONUS_PCT))
        # Soul Projection (see avatar.py): Formation Soul has no ally to buff solo, so it
        # buffs the caster's own STR/DEF instead — same "Defend Ally becomes self-Brace when
        # solo" adaptation Tank's Class Ability already uses. Demon Soul's amplified
        # low_hp_atk_bonus folds into the SAME below-50%-HP-gated flat bonus the passive
        # version already uses, just below, rather than a separate ungated add.
        sp = self._soul_projection_bonuses()
        if sp.get("sect_buff_str_pct"):
            stats["str_stat"] = round(stats["str_stat"] * (1 + sp["sect_buff_str_pct"]))
        if sp.get("sect_buff_def_pct"):
            stats["def_stat"] = round(stats["def_stat"] * (1 + sp["sect_buff_def_pct"]))
        low_hp_bonus = bonuses.get("low_hp_atk_bonus", 0) + sp.get("low_hp_atk_bonus", 0)
        if low_hp_bonus and 0 < self.player_hp < self.player_max_hp * 0.5:
            stats["str_stat"] += low_hp_bonus
        return stats

    def _persist_hp(self):
        self.game.db.set_hp(self.user_id, max(1, self.player_hp - self.hp_bonus))

    def _persist_qi(self):
        """Writes self.player_qi back to the DB — minus qi_bonus, mirroring _persist_hp
        (db.set_battle_qi's own clamp is against the un-bonused qi_stat column, so
        persisting the inflated number would just get silently cut back down)."""
        self.game.db.set_battle_qi(self.user_id, max(0.0, self.player_qi - self.qi_bonus))

    def _try_negate_fatal_hit(self) -> bool:
        if self.player["physique_tier"] != "Mythic":
            return False
        return self.game.db.try_use_daily_fatal_hit_negation(self.user_id)

    def _try_avatar_fatal_block(self) -> bool:
        """Nascent Soul Avatar's own once-daily fatal-blow shield — independent of Mythic
        Physique's charge above (a player with both gets two separate saves), gated only on
        having chosen an avatar soul at all, not on level or which soul."""
        if not self.player["avatar_soul"]:
            return False
        return self.game.db.try_use_daily_avatar_fatal_block(self.user_id)

    def _soul_projection_bonuses(self) -> dict:
        """Extra amounts Soul Projection adds on top of the passive while active this round
        -- empty when inactive or no soul chosen. Keyed the same as compute_equipment_bonuses'
        special dict for the keys _do_attack/_monster_turn read; Formation Soul's flat STR/
        DEF and Demon Soul's low_hp_atk_bonus are consumed directly in _player_combat_stats."""
        if self.soul_projection_rounds_remaining <= 0:
            return {}
        soul_name = self.player["avatar_soul"]
        soul = avatar.get_avatar_soul(soul_name)
        if soul is None:
            return {}
        multiplier = self.game.soul_projection_multiplier(self.user_id)
        return {
            key: avatar.soul_projection_bonus(soul_name, self.player["avatar_level"], key, multiplier)
            for key in avatar.SOUL_PROJECTION_KEYS.get(soul.name, ())
        }

    def _log_line(self, text: str):
        self.log.append(f"Wave {self.wave}: {text}")
        self.log = self.log[-MAX_LOG_LINES:]

    def _finish_round(self):
        if self.status == "fighting":
            self.round += 1
            if self.inspire_rounds_remaining > 0:
                self.inspire_rounds_remaining -= 1
            if self.soul_projection_rounds_remaining > 0:
                self.soul_projection_rounds_remaining -= 1
            self._start_round_timer()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your battlefield.", ephemeral=True)
            return False
        return True

    async def _refresh_message(self):
        if self.message is not None:
            try:
                await self.message.edit(embed=self.build_embed(), view=self)
            except discord.HTTPException:
                pass

    def _start_round_timer(self):
        self._round_epoch += 1
        asyncio.create_task(self._round_timeout(self._round_epoch))

    async def _round_timeout(self, epoch: int):
        await asyncio.sleep(ROUND_TIMEOUT_SECONDS)
        if self.status != "fighting" or epoch != self._round_epoch:
            return
        self.qi_empowered = False
        self._log_line("⏱️ You hesitate too long — your body swings on reflex!")
        self._do_attack()
        self._finish_round()
        self._build_components()
        await self._refresh_message()

    # -- combat resolution ------------------------------------------------------

    def _monster_turn(self, incoming_reduction: float = 0.0):
        if self.status != "fighting":
            return
        if self.monster_frozen_rounds > 0:
            self.monster_frozen_rounds -= 1
            self._log_line(f"❄️ {self.monster.name} is frozen and can't attack this round!")
            return
        bonuses = self._equipment_bonuses()
        beast_reduction = bonuses.get("beast_damage_reduction_pct", 0) if self.monster.monster_type == "Beast" else 0
        if beast_reduction:
            incoming_reduction = 1 - (1 - incoming_reduction) * (1 - beast_reduction)
        race_physique_reduction = chargen.race_physique_damage_reduction(
            self.player["race"], self.player["physique_tier"], self.player_hp / self.player_max_hp,
        )
        if race_physique_reduction:
            incoming_reduction = 1 - (1 - incoming_reduction) * (1 - race_physique_reduction)
        if incoming_reduction >= 1.0:
            self._log_line(f"🛡️ You fully block {self.monster.name}'s {self.monster.ability.name}!")
            return
        # Frost Soul's Soul Projection amplifies dodge/ignore-attack specifically on THIS
        # (incoming-attack) call — never the player's own _do_attack, which doesn't read
        # either kwarg at all.
        sp = self._soul_projection_bonuses()
        result = combat.resolve_attack(
            self.monster.stats(), self._player_combat_stats(),
            str_multiplier=self.monster.ability.str_multiplier, incoming_reduction=incoming_reduction,
            ignore_chance=bonuses.get("ignore_attack_chance", 0) + sp.get("ignore_attack_chance", 0),
            dodge_chance_bonus=bonuses.get("dodge_chance_pct", 0) + sp.get("dodge_chance_pct", 0),
            lifesteal_percent=self.monster.ability.lifesteal_percent,
        )
        if not result.hit:
            self._log_line(f"❌ {self.monster.name} uses {self.monster.ability.name} but misses!")
        elif result.dodged:
            self._log_line(f"💨 You dodge {self.monster.name}'s {self.monster.ability.name}!")
        elif result.ignored:
            self._log_line(f"🛡️ Your Gu shrugs off {self.monster.name}'s {self.monster.ability.name} entirely!")
        elif self.player_hp - result.damage <= 0 and (self._try_negate_fatal_hit() or self._try_avatar_fatal_block()):
            self._log_line(f"✨ {self.monster.name}'s {self.monster.ability.name} should have been fatal — your body refuses to fall!")
        else:
            self.player_hp = max(0, self.player_hp - result.damage)
            self._persist_hp()
            crit = " (Critical!)" if result.crit else ""
            heal_text = ""
            if result.heal:
                self.monster_hp = min(self.monster_max_hp, self.monster_hp + result.heal)
                heal_text = f" It recovers {result.heal} HP."
            self._log_line(f"🩸 {self.monster.name} uses {self.monster.ability.name} for {result.damage} damage{crit}.{heal_text}")
        if self.player_hp <= 0:
            self.status = "defeat"
            self.player_hp = self.game.db.set_hp(self.user_id, 1)
            ward_name = self.game.check_and_consume_defeat_ward(self.user_id)
            if ward_name:
                self.qi_lost_on_death = 0.0
                self._log_line(f"✨ **{ward_name}** activates — you're struck down but the Qi loss is warded away!")
            elif self.game.check_and_consume_worldly_escape(self.user_id):
                self.qi_lost_on_death = 0.0
                self._log_line("✨ **Worldly Escape Gu** activates — you're struck down but the Qi loss is escaped entirely!")
            else:
                # Consolidated single read of the generic pool (root/physique/Gu/avatar
                # soul/avatar gear all fold in there now — see
                # GameManager.compute_equipment_bonuses) instead of separate manual reads
                # per source, which would double-count once this key also lives in
                # SPECIAL_BONUS_KEYS.
                reduction = bonuses.get("death_qi_loss_reduction_pct", 0)
                self.qi_lost_on_death, _ = self.game.db.apply_death_penalty(self.user_id, reduction_pct=reduction)
                self._log_line(f"💀 You are struck down, losing {self.qi_lost_on_death:,.2f} qi.")
            self._end_run()

    def _do_attack(self, str_multiplier: float = 1.0, label: str = "Attack", guaranteed_hit: bool = False, freeze_chance: float = 0.0):
        bonuses = self._equipment_bonuses()
        # Demon Soul's execute_damage_pct (passive + Soul Projection's amplified delta) only
        # applies once the target's already below half HP, mirroring hunt.py's identical
        # caller-side pattern.
        sp = self._soul_projection_bonuses()
        damage_pct_bonus = bonuses.get("physical_damage_pct", 0) + bonuses.get("total_damage_pct", 0)
        if self.monster_hp > 0 and self.monster_hp < self.monster_max_hp * 0.5:
            damage_pct_bonus += bonuses.get("execute_damage_pct", 0) + sp.get("execute_damage_pct", 0)
        result = combat.resolve_attack(
            self._player_combat_stats(), self.monster.stats(), str_multiplier=str_multiplier, guaranteed_hit=guaranteed_hit,
            crit_chance_bonus=bonuses.get("crit_chance_pct", 0) + sp.get("crit_chance_pct", 0),
            crit_damage_bonus=bonuses.get("crit_damage_pct", 0) + sp.get("crit_damage_pct", 0),
            lifesteal_percent=bonuses.get("lifesteal_percent", 0) + sp.get("lifesteal_percent", 0),
            damage_pct_bonus=damage_pct_bonus,
            armor_penetration_pct=bonuses.get("armor_penetration_pct", 0) + sp.get("armor_penetration_pct", 0),
            max_dodge_chance=combat.MONSTER_MAX_DODGE_CHANCE,
        )
        if not result.hit:
            self._log_line(f"❌ You use {label} but miss!")
        elif result.dodged:
            self._log_line(f"💨 {self.monster.name} dodges your {label}!")
        else:
            self.monster_hp = max(0, self.monster_hp - result.damage)
            crit = " (Critical!)" if result.crit else ""
            heal_text = ""
            if result.heal:
                self.player_hp = min(self.player_max_hp, self.player_hp + result.heal)
                self._persist_hp()
                heal_text = f" 💚 +{result.heal} HP."
            self._log_line(f"⚔️ You use {label} for {result.damage} damage{crit}.{heal_text}")
            if freeze_chance and self.monster_hp > 0 and random.random() < freeze_chance:
                self.monster_frozen_rounds = max(self.monster_frozen_rounds, 1)
                self._log_line(f"❄️ {self.monster.name} is frozen solid and will miss its next attack!")
        if self.monster_hp <= 0:
            self._on_wave_clear()
        else:
            self._monster_turn()

    def _on_wave_clear(self):
        bonuses = self._equipment_bonuses()
        loot_chance_multiplier = 1.0 + bonuses.get("loot_chance_bonus_pct", 0)
        root_spec = chargen.get_root_spec(self.player["root_name"])
        beast_qty_bonus = root_spec.stat_bonuses.get("beast_material_quantity_bonus_pct", 0) if root_spec else 0
        loot = roll_loot(self.monster, chance_multiplier=loot_chance_multiplier, beast_material_quantity_bonus_pct=beast_qty_bonus)
        effective_luck = self.player["luck_stat"] + bonuses["stats"]["luck_stat"]
        canon_drop = canon_gu.roll_canon_gu_drop(self.monster.gu_rank, "normal", luck_bonus=min(0.05, effective_luck * 0.001))
        if canon_drop:
            loot[canon_drop] = loot.get(canon_drop, 0) + 1
        for item_name, quantity in loot.items():
            self.game.db.add_item(self.user_id, item_name, quantity)
        wave_reward_text = self.game.resolve_battlefield_wave_clear(self.user_id, self.display_name, self.discovery, self.wave)
        # Spirit Severing Dao Marks (see GameManager.grant_dao_marks) -- once per wave clear,
        # mirroring hunt.py's own per-kill grant; silently a no-op below Spirit Severing.
        self.game.grant_dao_marks(self.user_id, self.player)
        self._log_line(f"💥 {self.monster.name} falls! Also: {wave_reward_text}.")
        self.wave_log.append(f"Wave {self.wave}: {self.monster.name} defeated — {wave_reward_text}.")
        self.wave += 1
        self.monster = self._roll_wave_monster()
        self.monster_hp = self.monster.hp
        self.monster_max_hp = self.monster.hp
        self._log_line(f"⚔️ A new challenger emerges: **{self.monster.name}**!")

    def _end_run(self):
        """Called on defeat or a successful flee -- pays out the scaled final reward and
        clears the discovery, either way."""
        self.final_reward_text = self.game.resolve_battlefield_final_reward(self.user_id, self.display_name, self.discovery, self.waves_cleared)
        self.game.finish_discovery(self.user_id, self.discovery["discovery_id"])

    # -- action handlers ---------------------------------------------------

    def _consume_empower(self) -> bool:
        used = self.qi_empowered and self.player_qi >= EMPOWER_QI_COST
        if used:
            self.player_qi -= EMPOWER_QI_COST
            self._persist_qi()
        self.qi_empowered = False
        return used

    async def _on_attack(self, interaction: discord.Interaction):
        empowered = self._consume_empower()
        if empowered:
            self._log_line("✨ You channel Qi to guarantee your strike!")
        self._do_attack(guaranteed_hit=empowered)
        self._finish_round()
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_guard(self, interaction: discord.Interaction):
        empowered = self._consume_empower()
        if empowered:
            self._log_line("✨ You channel Qi to fully brace against the blow!")
        else:
            self._log_line("🛡️ You brace for the next blow.")
        self._monster_turn(incoming_reduction=1.0 if empowered else GUARD_DAMAGE_REDUCTION)
        self._finish_round()
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_toggle_empower(self, interaction: discord.Interaction):
        self.qi_empowered = not self.qi_empowered
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_flee(self, interaction: discord.Interaction):
        # Always succeeds -- unlike hunt.py/raid.py's SPD-gated flee roll, /battlefield's
        # Withdraw is a guaranteed "bank what you've earned so far" escape hatch, per explicit
        # request.
        self.status = "fled"
        self._log_line("🏃 You withdraw from the battlefield with what you've earned!")
        self._end_run()
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_class_ability(self, interaction: discord.Interaction):
        class_name = self.player["character_class"]
        if class_name == "Tank":
            self._log_line("🛡️ You brace with unshakable resolve — no ally around to protect but yourself!")
            self._monster_turn(incoming_reduction=BRACE_DAMAGE_REDUCTION)
            self._finish_round()
        elif class_name == "Support":
            self.inspire_rounds_remaining = INSPIRE_DURATION_ROUNDS
            self._log_line("✨ You channel Inspire — your own STR and DEF surge!")
            self._monster_turn()
            self._finish_round()
        elif class_name == "Frostbinder":
            self._log_line("❄️ You channel Freeze!")
            self._do_attack(str_multiplier=FREEZE_STR_MULTIPLIER, label="Freeze", freeze_chance=FREEZE_PROC_CHANCE)
            self._finish_round()
        else:
            await interaction.response.send_message(
                "You haven't chosen a class yet — run `/choose_class` to unlock a class ability.", ephemeral=True,
            )
            return
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_soul_projection(self, interaction: discord.Interaction):
        """Independent of class -- gated on having chosen an avatar soul via /avatar instead.
        Not a pure buff-and-pass like Inspire: the duration is set BEFORE _do_attack runs, so
        this same activation strikes immediately with the just-activated buff already live
        (_soul_projection_bonuses reads soul_projection_rounds_remaining, which is already
        positive by the time _do_attack calls it)."""
        soul = avatar.get_avatar_soul(self.player["avatar_soul"])
        if soul is None:
            await interaction.response.send_message(
                "Your avatar hasn't chosen a soul yet — run `/avatar` to awaken it.", ephemeral=True,
            )
            return
        if self.player_qi < avatar.SOUL_PROJECTION_QI_COST:
            await interaction.response.send_message(
                f"Not enough battle Qi for Soul Projection (needs {avatar.SOUL_PROJECTION_QI_COST:,}).", ephemeral=True,
            )
            return
        self.player_qi -= avatar.SOUL_PROJECTION_QI_COST
        self._persist_qi()
        self.soul_projection_rounds_remaining = avatar.soul_projection_duration(soul)
        self._log_line(f"🌀 You channel {avatar.SOUL_PROJECTION_NAME} — {soul.name}'s power surges through you!")
        self._do_attack(label=avatar.SOUL_PROJECTION_NAME)
        self._finish_round()
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_use_potion(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        item_name = select.values[0]
        if item_name == "none":
            await interaction.response.defer()
            return
        ok, message = self.game.use_item(self.user_id, self.display_name, item_name)
        if ok:
            self.potions_used += 1
            fresh = self.game.get_player_stats(self.user_id, self.display_name)
            self.player_hp = min(self.player_max_hp, fresh["hp"] + self.hp_bonus)
            self._log_line(f"🧪 You use {item_name} — {message}")
            self._monster_turn()
        else:
            self._log_line(f"❌ Couldn't use {item_name}: {message}")
        self._finish_round()
        self._build_components()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self):
        if self.status == "fighting":
            self.status = "fled"
            self._end_run()
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(embed=self.build_embed(), view=self)
            except discord.HTTPException:
                pass

    # -- UI building ---------------------------------------------------

    def _build_components(self):
        self.clear_items()
        active = self.status == "fighting"

        buttons = [
            ("Attack", "⚔️", discord.ButtonStyle.primary, self._on_attack),
            ("Guard", "🛡️", discord.ButtonStyle.secondary, self._on_guard),
            ("Withdraw", "🏃", discord.ButtonStyle.danger, self._on_flee),
        ]
        for label, emoji, style, callback in buttons:
            button = discord.ui.Button(label=label, emoji=emoji, style=style, row=0, disabled=not active)
            button.callback = callback
            self.add_item(button)

        empower_button = discord.ui.Button(
            label=f"Empower ({EMPOWER_QI_COST})", emoji="✨",
            style=discord.ButtonStyle.success if self.qi_empowered else discord.ButtonStyle.secondary,
            row=0, disabled=not active or (not self.qi_empowered and self.player_qi < EMPOWER_QI_COST),
        )
        empower_button.callback = self._on_toggle_empower
        self.add_item(empower_button)

        class_button = discord.ui.Button(
            label="Class Ability", emoji="🎭", style=discord.ButtonStyle.success, row=1, disabled=not active,
        )
        class_button.callback = self._on_class_ability
        self.add_item(class_button)

        # Nascent Soul Avatar's Soul Projection (see avatar.py).
        soul_projection_button = discord.ui.Button(
            label=f"Soul Projection ({avatar.SOUL_PROJECTION_QI_COST:,})", emoji="🌀",
            style=discord.ButtonStyle.success, row=1,
            disabled=not active or not self.player["avatar_soul"] or self.player_qi < avatar.SOUL_PROJECTION_QI_COST,
        )
        soul_projection_button.callback = self._on_soul_projection
        self.add_item(soul_projection_button)

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
            options=potion_options[:25] or [discord.SelectOption(label="None available", value="none")],
            disabled=not potion_options or cap_reached or not active,
            row=2,
        )
        potion_select.callback = self._on_use_potion
        self.add_item(potion_select)

    def build_embed(self) -> discord.Embed:
        m = self.monster
        monster_pct = int(100 * max(0, self.monster_hp) / self.monster_max_hp)
        player_pct = int(100 * max(0, self.player_hp) / self.player_max_hp)
        qi_pct = int(100 * max(0, self.player_qi) / max(1, self.player_max_qi))

        description = f"Rank **{self.discovery['rank']}** • Difficulty **{self.discovery['difficulty']}** • Waves cleared: **{self.waves_cleared}**"
        if self.inspire_rounds_remaining > 0:
            description += f"\n✨ **Inspire active** — your STR/DEF are boosted ({self.inspire_rounds_remaining} round(s) left)."
        if self.soul_projection_rounds_remaining > 0:
            description += f"\n🌀 **Soul Projection active** — your avatar's power surges ({self.soul_projection_rounds_remaining} round(s) left)."
        embed = discord.Embed(
            title=f"⚔️ {self.discovery['theme']} • Wave {self.wave} • {STATUS_LABELS[self.status]}",
            description=description,
            color=STATUS_COLORS[self.status],
        )
        embed.set_thumbnail(url=self.avatar_url)

        frozen_note = " ❄️ *Frozen*" if self.monster_frozen_rounds > 0 else ""
        embed.add_field(
            name=f"🐗 {m.name}{frozen_note}",
            value=(
                f"❤️ HP `{max(0, self.monster_hp):.0f} / {self.monster_max_hp:.0f}` • {monster_pct}%\n"
                f"`{render_bar(self.monster_hp, self.monster_max_hp)}`\n"
                f"🎯 Next: **{m.ability.name}** — {m.ability.description}"
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

        if self.status == "defeat":
            embed.add_field(
                name="💀 Outcome",
                value=(
                    f"You were struck down after clearing **{self.waves_cleared}** wave(s), losing **{self.qi_lost_on_death:,.2f} qi**.\n"
                    f"🎁 Final reward: {self.final_reward_text}"
                ),
                inline=False,
            )
        elif self.status == "fled":
            embed.add_field(
                name="🏃 Outcome",
                value=f"You withdrew after clearing **{self.waves_cleared}** wave(s).\n🎁 Final reward: {self.final_reward_text}",
                inline=False,
            )

        embed.set_footer(
            text=f"Choose an action — go quiet for {ROUND_TIMEOUT_SECONDS}s and you'll auto-attack on reflex instead."
            if self.status == "fighting" else "This battlefield has ended."
        )
        return embed
