import asyncio
import dataclasses
import os
import random

import discord

from . import avatar, canon_gu, chargen, combat, dao_paths, white_heaven
from .base_view import GameView
from .equipment import EQUIPMENT, gear_power_score, parse_gu_name
from .items import ITEMS, roll_essence_restoration_pill_drop
from .monsters import MONSTERS, roll_loot
from .raid import (
    FREEZE_PROC_CHANCE,
    FREEZE_STR_MULTIPLIER,
    INSPIRE_DEF_BONUS_PCT,
    INSPIRE_DURATION_ROUNDS,
    INSPIRE_STR_BONUS_PCT,
)
from .raid import DEFEND_ALLY_DAMAGE_REDUCTION as _BRACE_EXTRA_REDUCTION
from .ui_utils import render_bar

FLEE_BASE_CHANCE = 0.5
FLEE_CHANCE_PER_SPD_DIFF = 0.02
MIN_FLEE_CHANCE = 0.1
MAX_FLEE_CHANCE = 0.9

GUARD_DAMAGE_REDUCTION = 0.5  # fraction of incoming damage blocked while guarding, when not Qi-empowered
POTION_USE_CAP = 3  # per hunt, tunable — stops potion-spam from trivializing fights
MAX_LOG_LINES = 4

# Class Ability (see character_class.py / HuntView._on_class_ability) — the same abilities
# raid.py gives each class, adapted for a solo fight with no allies to target:
#   Tank's Defend Ally    -> Brace: no ally to redirect hits onto, so instead brace with the
#                            same toughness bonus stacked on top of a normal Guard.
#   Support's Inspire     -> buffs your own STR/DEF for a few rounds (still costs your
#                            attack that round, same as in a raid).
#   Frostbinder's Freeze  -> a weaker attack with a chance to freeze the monster, making it
#                            skip its next attack — needs no adaptation, it already only
#                            ever targeted the enemy.
# Reuses raid.py's tuning constants directly rather than duplicating magic numbers, so the
# two stay in lockstep if raid's balance ever changes.
BRACE_DAMAGE_REDUCTION = 1 - (1 - GUARD_DAMAGE_REDUCTION) * (1 - _BRACE_EXTRA_REDUCTION)

# Spend battle Qi to guarantee your next Attack lands, or fully block your next Guard.
EMPOWER_QI_COST = 15

# If no action is taken within this long, the character auto-attacks on the player's behalf
# and the clock restarts — repeating every round until the fight actually ends (victory or
# defeat), the same AFK policy /raid already uses. This exists so a player who's losing can't
# just stop interacting to dodge the defeat penalty (fleeing costs nothing; a forced auto-
# attack still risks the real death penalty). Staleness is tracked with an epoch counter
# rather than cancelling the pending asyncio timer task directly — see raid.py's identical
# pattern for why.
HUNT_ROUND_TIMEOUT_SECONDS = 30

STATUS_LABELS = {"fighting": "Fighting", "victory": "Victory!", "defeat": "Defeat", "fled": "Fled"}
STATUS_COLORS = {
    "fighting": discord.Color.dark_gold(),
    "victory": discord.Color.green(),
    "defeat": discord.Color.dark_red(),
    "fled": discord.Color.greyple(),
}


class HuntView(GameView):
    def __init__(
        self, user_id: int, game, player, display_name: str, avatar_url: str, monster_name: str,
        region_modifiers: dict = None,
    ):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.game = game
        self.player = player
        self.display_name = display_name
        self.avatar_url = avatar_url
        base_monster = MONSTERS[monster_name]
        # world_regions.py's Northern Plains (always-on) / Eastern Sea, Western Desert,
        # Central Continent (chance-based "hoard guardian") passives — see
        # GameManager.region_encounter_modifiers. A scaled COPY of the monster is built here
        # rather than mutating the shared MONSTERS catalog instance, which every other hunt
        # of the same monster also reads.
        self.region_modifiers = region_modifiers or {}
        stat_multiplier = self.region_modifiers.get("stat_multiplier", 1.0)
        if stat_multiplier != 1.0:
            self.monster = dataclasses.replace(
                base_monster,
                hp=max(1, round(base_monster.hp * stat_multiplier)),
                atk_stat=max(1, round(base_monster.atk_stat * stat_multiplier)),
                str_stat=max(1, round(base_monster.str_stat * stat_multiplier)),
                def_stat=max(1, round(base_monster.def_stat * stat_multiplier)),
                spd_stat=max(1, round(base_monster.spd_stat * stat_multiplier)),
            )
        else:
            self.monster = base_monster

        self.round = 1
        self.monster_hp = self.monster.hp
        self.monster_max_hp = self.monster.hp
        # A named root's AND a named physique's own combat mechanics (see character_data.
        # CharacterTraitSpec) — both resolved once here since neither can change mid-
        # encounter. Most stat_bonuses keys are read through self._trait_bonus(key) (sums
        # both sources); the Fire root family's own battle-Qi trigger and Fire's fire_str
        # fields are root-only (no physique family reuses that shape yet), so those two still
        # read root_spec directly.
        self.root_spec = chargen.get_root_spec(self.player["root_name"])
        self.physique_spec = chargen.get_physique_spec(self.player["physique_name"])
        # HP and battle Qi are both persistent and regenerate slowly in real time
        # (see settle_hp_regen / settle_battle_qi) — neither refills at the start of every hunt.
        # Equipped gear's flat "hp"/"qi_stat" stat_bonuses (e.g. tiered Gu's qi_pct, or an
        # Artifact's qi_stat) are folded in here as a live overlay on top of the persisted
        # (gear-independent) hp/max_hp and battle_qi/qi_stat columns, the same way
        # atk/str/def/spd/luck bonuses already work — see _persist_hp/_persist_qi for why
        # writes back to the DB have to subtract them back out again rather than storing the
        # inflated number.
        equip_bonuses = self.game.compute_equipment_bonuses(user_id)["stats"]
        self.hp_bonus = equip_bonuses["hp"]
        hp_settled = self.game.db.settle_hp_regen(user_id)
        self.player_hp = hp_settled["hp"] + self.hp_bonus
        self.player_max_hp = hp_settled["max_hp"] + self.hp_bonus
        self.qi_bonus = equip_bonuses["qi_stat"]
        # Sturdy Frame-family physique's battle_qi_regen_bonus_pct — a rate multiplier on the
        # passive real-time regen itself, applied right here where it's settled.
        settled = self.game.db.settle_battle_qi(user_id, regen_rate_bonus_pct=self._trait_bonus("battle_qi_regen_bonus_pct"))
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
        self._qi_spent_this_encounter = 0.0
        self._fire_root_str_bonus_pending = False
        self._fire_root_triggered = False
        # Fire Dao Path burn (see dao_paths.fire_burn_tick_damage) -- seeded on a landed hit,
        # ticks once per round via _finish_round/_apply_pending_burn_tick regardless of which
        # action the player takes that round.
        self._burn_damage_per_tick = 0
        self._burn_ticks_remaining = 0
        # Common-tier physique combat state (see character_data.py's Common physique section
        # for the 9 families these back) — all encounter-scoped, reset fresh every hunt.
        self._guard_stacks = 0  # Iron Skin family, capped at 2
        self._dodge_momentum_pending = False  # Swift Foot family
        self._dodge_momentum_triggered = False  # only the FIRST dodge each encounter arms it
        self._attack_count = 0  # Strong Bone family (every 3rd successful basic Attack)
        self._first_gu_use_discounted = False  # Sturdy Frame family
        self._guard_or_potion_qi_restored = False  # River Walker family, once per encounter
        # Heavenly Solar/Lunar Physique (Unique) -- each landed basic Attack adds a stack,
        # capped at 5 (5 x 4%/5% hits the confirmed 20%/25% caps). Same encounter-scoped
        # shape as Iron Skin's own _guard_stacks above.
        self._solar_stacks = 0
        self._lunar_stacks = 0
        # Blazing Glory Sunfire Physique (Unique) -- a second, independent burn source from
        # Fire Dao Path's own _burn_damage_per_tick/_burn_ticks_remaining above (a player
        # could have both a Fire Dao Path AND this physique at once), same "refreshes, doesn't
        # stack, on every landed hit" shape, ticked alongside it in _apply_pending_burn_tick.
        self._sunfire_burn_damage_per_tick = 0
        self._sunfire_burn_ticks_remaining = 0
        # Uncommon/Rare-tier physique combat state (see character_data.py for the families).
        self._first_empower_discounted = False  # Thunder Muscle family
        self._flee_reroll_used = False  # Void family
        self._gu_miss_refunded = False  # Moonlight family, once per encounter
        # Clear Mind family's encounter-start adaptive stat — computed once here (raw stats,
        # not equipment-adjusted, to avoid depending on _player_combat_stats before it can
        # itself apply this bonus) rather than re-decided every round.
        self._adaptive_stat_key = None
        if self._trait_bonus("encounter_start_adaptive_stat_pct"):
            ratios = {
                "atk_stat": self.player["atk_stat"] / max(1, self.monster.atk_stat),
                "def_stat": self.player["def_stat"] / max(1, self.monster.def_stat),
                "spd_stat": self.player["spd_stat"] / max(1, self.monster.spd_stat),
            }
            self._adaptive_stat_key = min(ratios, key=ratios.get)
        self.log: list = []
        self.status = "fighting"
        self.potions_used = 0
        self.loot: dict = {}
        self.message: discord.Message = None
        self._round_epoch = 0  # bumped each time a round's timer (re)starts, to detect stale timeouts

        self.game.apply_encounter_start_bonuses(user_id, display_name)
        self._build_components()
        self._start_round_timer()

    # -- helpers -----------------------------------------------------------

    def _clear_active_hunt(self):
        """Called from every terminal-status transition (defeat/victory/fled/timeout) so
        GameManager.has_active_hunt lets the player start a new /hunt again — see
        cog.py's hunt command / manager.py's ACTIVE_HUNT_STALE_SECONDS block."""
        self.game.db.clear_active_hunt(self.user_id)

    def _equipment_bonuses(self) -> dict:
        return self.game.compute_equipment_bonuses(self.user_id)

    def _trait_bonus(self, key: str) -> float:
        """A named root's AND a named physique's own stat_bonuses value for `key` (see
        character_data.CharacterTraitSpec), PLUS the equipped Gu's own stat_bonuses value for
        it — mirrors GameManager._trait_bonus's own root/physique/Gu fold-in exactly (that
        version already included Gu; this one didn't until White Heaven's Heavenly
        Reflection Gu needed retaliation_damage_pct to actually work through a Gu, not just
        root/physique)."""
        root_value = self.root_spec.stat_bonuses.get(key, 0) if self.root_spec else 0
        physique_value = self.physique_spec.stat_bonuses.get(key, 0) if self.physique_spec else 0
        gu_item_name = self.game.db.get_equipped(self.user_id).get("gu_ability")
        gu = EQUIPMENT.get(gu_item_name) if gu_item_name else None
        gu_value = gu.stat_bonuses.get(key, 0) if gu else 0
        return root_value + physique_value + gu_value

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
        # Savage Boar Gu-style passive: bonus STR while under half HP.
        low_hp_bonus = bonuses.get("low_hp_atk_bonus", 0) + sp.get("low_hp_atk_bonus", 0)
        if low_hp_bonus and 0 < self.player_hp < self.player_max_hp * 0.5:
            stats["str_stat"] += low_hp_bonus
        # Phoenix Feather-family physique: the same "below 50% HP" threshold, but a %
        # bonus rather than a flat one.
        low_hp_str_pct = self._trait_bonus("low_hp_str_pct_bonus")
        if low_hp_str_pct and 0 < self.player_hp < self.player_max_hp * 0.5:
            stats["str_stat"] = round(stats["str_stat"] * (1 + low_hp_str_pct))
        # Clear Mind/Star-family physique's encounter-start adaptive stat (see __init__) —
        # Star family reuses this exact mechanic rather than a near-duplicate "lowest of my
        # OWN raw stats" variant, since the practical effect (boost your weakest combat
        # stat at the start of the fight) is the same either way.
        if self._adaptive_stat_key:
            stats[self._adaptive_stat_key] = round(stats[self._adaptive_stat_key] * (1 + self._trait_bonus("encounter_start_adaptive_stat_pct")))
        return stats

    def _equipped_gu(self):
        gu_name = self.game.get_equipped(self.user_id).get("gu_ability")
        return EQUIPMENT.get(gu_name) if gu_name else None

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

    def _persist_hp(self):
        """Writes self.player_hp back to the DB — minus hp_bonus, since the stored hp/max_hp
        columns stay gear-independent (db.set_hp's own clamp is against the un-bonused
        max_hp, so persisting the inflated number would just get silently cut back down)."""
        self.game.db.set_hp(self.user_id, max(1, self.player_hp - self.hp_bonus))

    def _persist_qi(self):
        """Writes self.player_qi back to the DB — minus qi_bonus, mirroring _persist_hp
        (db.set_battle_qi's own clamp is against the un-bonused qi_stat column, so
        persisting the inflated number would just get silently cut back down)."""
        self.game.db.set_battle_qi(self.user_id, max(0.0, self.player_qi - self.qi_bonus))

    def _try_negate_fatal_hit(self) -> bool:
        """Mythic Physique's "ignore the first fatal hit each day" — True (and consumes the
        day's charge) only for a Mythic-physique player who hasn't already used it today."""
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

    def _log_line(self, text: str):
        self.log.append(f"Round {self.round}: {text}")
        self.log = self.log[-MAX_LOG_LINES:]

    def _apply_pending_burn_tick(self):
        """Fire Dao Path: a burn seeded by a landed hit (see _do_attack) ticks once per round,
        on top of whatever the player's own action this round did -- can finish the monster off
        on its own, same as any other damage source."""
        if self._burn_ticks_remaining <= 0 or self.monster_hp <= 0:
            return
        damage = min(self.monster_hp, self._burn_damage_per_tick)
        self.monster_hp -= damage
        self._burn_ticks_remaining -= 1
        self._log_line(f"🔥 {self.monster.name} burns for {damage} damage!")
        if self.monster_hp <= 0:
            self._handle_victory()

    def _apply_pending_sunfire_tick(self):
        """Blazing Glory Sunfire Physique: an independent burn source from Fire Dao Path's own
        above -- seeded on a landed hit (see _do_attack), ticks once per round the same way."""
        if self._sunfire_burn_ticks_remaining <= 0 or self.monster_hp <= 0:
            return
        damage = min(self.monster_hp, self._sunfire_burn_damage_per_tick)
        self.monster_hp -= damage
        self._sunfire_burn_ticks_remaining -= 1
        self._log_line(f"☀️ {self.monster.name} burns in sunfire for {damage} damage!")
        if self.monster_hp <= 0:
            self._handle_victory()

    def _finish_round(self):
        if self.status == "fighting":
            self._apply_pending_burn_tick()
        if self.status == "fighting":
            self._apply_pending_sunfire_tick()
        if self.status == "fighting":
            self.round += 1
            if self.inspire_rounds_remaining > 0:
                self.inspire_rounds_remaining -= 1
            if self.soul_projection_rounds_remaining > 0:
                self.soul_projection_rounds_remaining -= 1
            self._start_round_timer()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your hunt.", ephemeral=True)
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
        await asyncio.sleep(HUNT_ROUND_TIMEOUT_SECONDS)
        if self.status != "fighting" or epoch != self._round_epoch:
            return  # this round already resolved on its own (or the hunt ended) before this fired
        self.qi_empowered = False  # an unused Empower doesn't carry over into a forced auto-attack
        self._log_line("⏱️ You hesitate too long — your body swings on reflex!")
        # _finish_round (and the create_task it can trigger via _start_round_timer) must run
        # on the main thread -- asyncio.create_task requires a running loop in the CURRENT
        # thread, which a asyncio.to_thread worker never has.
        await asyncio.to_thread(self._do_attack)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        await self._refresh_message()

    # -- combat resolution ---------------------------------------------------

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
        # Rockman's "-15% dmg above 50% HP" and Rare Physique's small flat reduction.
        race_physique_reduction = chargen.race_physique_damage_reduction(
            self.player["race"], self.player["physique_tier"], self.player_hp / self.player_max_hp,
        )
        if race_physique_reduction:
            incoming_reduction = 1 - (1 - incoming_reduction) * (1 - race_physique_reduction)
        # Iron Skin-family physique's Guard stacks (permanent for the rest of the encounter,
        # not just this hit) and Stone Muscle-family physique's high-HP damage reduction.
        guard_stack_reduction = self._trait_bonus("guard_stack_def_pct") * self._guard_stacks
        if guard_stack_reduction:
            incoming_reduction = 1 - (1 - incoming_reduction) * (1 - guard_stack_reduction)
        if self.player_hp > self.player_max_hp * 0.6:
            high_hp_reduction = self._trait_bonus("high_hp_damage_reduction_pct")
            if high_hp_reduction:
                incoming_reduction = 1 - (1 - incoming_reduction) * (1 - high_hp_reduction)
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
            max_dodge_chance=combat.MAX_DODGE_CHANCE + bonuses.get("dodge_cap_bonus_pct", 0),
            lifesteal_percent=self.monster.ability.lifesteal_percent,
        )
        if not result.hit:
            self._log_line(f"❌ {self.monster.name} uses {self.monster.ability.name} but misses!")
        elif result.dodged:
            self._log_line(f"💨 You dodge {self.monster.name}'s {self.monster.ability.name}!")
            # Swift Foot-family physique's Momentum — only the FIRST dodge each encounter
            # arms the bonus (see _do_attack for where it's consumed).
            if not self._dodge_momentum_triggered and self._trait_bonus("dodge_momentum_str_bonus_pct"):
                self._dodge_momentum_pending = True
                self._dodge_momentum_triggered = True
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
            # Immovable Mountain Physique: surviving a landed hit reflects a portion of the
            # damage taken straight back at the attacker -- guaranteed (no separate hit/dodge/
            # crit roll of its own), same simplicity as the burn-tick mechanics above.
            if self.player_hp > 0 and self.monster_hp > 0:
                retaliation_pct = self._trait_bonus("retaliation_damage_pct")
                if retaliation_pct > 0:
                    retaliation_damage = max(1, round(result.damage * retaliation_pct))
                    self.monster_hp = max(0, self.monster_hp - retaliation_damage)
                    self._log_line(f"🪨 You retaliate for {retaliation_damage} damage!")
                    if self.monster_hp <= 0:
                        self._handle_victory()
        if self.player_hp <= 0:
            self.status = "defeat"
            self._clear_active_hunt()
            self.player_hp = self.game.db.set_hp(self.user_id, 1)
            ward_name = self.game.check_and_consume_defeat_ward(self.user_id)
            escape_gu_name = None if ward_name else self.game.check_and_consume_worldly_escape(self.user_id)
            if ward_name:
                self.qi_lost_on_death = 0.0
                self._log_line(f"✨ **{ward_name}** activates — you're struck down but the Qi loss is warded away!")
            elif escape_gu_name:
                self.qi_lost_on_death = 0.0
                self._log_line(f"✨ **{escape_gu_name}** activates — you're struck down but the Qi loss is escaped entirely!")
            else:
                # Consolidated single read of the generic pool (root/physique/Gu/avatar
                # soul/avatar gear all fold in there now — see
                # GameManager.compute_equipment_bonuses) instead of separate manual reads
                # per source, which would double-count once this key also lives in
                # SPECIAL_BONUS_KEYS.
                reduction = bonuses.get("death_qi_loss_reduction_pct", 0)
                self.qi_lost_on_death, _ = self.game.db.apply_death_penalty(self.user_id, reduction_pct=reduction)
                self._log_line(f"💀 You are struck down and forced to retreat, losing {self.qi_lost_on_death:,.2f} qi.")

    def _do_attack(self, str_multiplier: float = 1.0, label: str = "Attack", guaranteed_hit: bool = False, freeze_chance: float = 0.0, is_technique: bool = False):
        bonuses = self._equipment_bonuses()
        # Gu abilities / class abilities count as "technique" damage; the plain Attack button
        # is "physical" — see manual_view.EFFECT_LABELS' technique_damage_pct/physical_damage_pct.
        damage_pct_bonus = (bonuses.get("technique_damage_pct", 0) if is_technique else bonuses.get("physical_damage_pct", 0)) + bonuses.get("total_damage_pct", 0)
        # A Lightning-family root's empower_damage_pct only applies to an actually-Empowered
        # attack; a Fire-family root's battle-Qi trigger (see _track_battle_qi_spent) applies
        # once, to whichever attack comes next, consumed here regardless of hit/miss — same
        # "spend it on your next swing either way" convention Brute Force Longhorn Beetle Gu's
        # own STR-buff ability already uses.
        if guaranteed_hit:
            damage_pct_bonus += self._trait_bonus("empower_damage_pct")
        if self._fire_root_str_bonus_pending:
            damage_pct_bonus += self.root_spec.fire_battle_qi_str_bonus_pct
            self._fire_root_str_bonus_pending = False
        # A Strength-family root's beast_damage_pct only applies against Beast-type monsters
        # — the offensive counterpart to Gu's existing beast_damage_reduction_pct (defensive).
        if self.monster.monster_type == "Beast":
            damage_pct_bonus += self._trait_bonus("beast_damage_pct")
        # Tribulation Lightning Gu (see content/canon_gu_white_heaven.py) -- same elite-gated
        # boss_damage_bonus_pct hookup as team_battle.py's identical addition.
        if self.monster.elite:
            damage_pct_bonus += bonuses.get("boss_damage_bonus_pct", 0)
        # Swift Foot-family physique's Momentum, consumed on whichever basic Attack comes
        # next after the triggering dodge (hit or miss, same convention as the Fire root's
        # own pending-bonus trigger); Strong Bone-family physique's every-3rd-basic-Attack
        # bonus. Both are specifically "basic Attack" only, not Gu/class abilities.
        lunar_armor_pen = 0.0
        if label == "Attack":
            if self._dodge_momentum_pending:
                damage_pct_bonus += self._trait_bonus("dodge_momentum_str_bonus_pct")
                self._dodge_momentum_pending = False
            self._attack_count += 1
            if self._attack_count % 3 == 0:
                damage_pct_bonus += self._trait_bonus("every_third_attack_bonus_pct")
            # Heavenly Solar/Lunar Physique -- both read the stack count BEFORE this attack
            # (grown by prior landed basic Attacks), same "read old count, increment after a
            # landed hit" order Iron Skin's own guard_stack_reduction uses.
            damage_pct_bonus += self._trait_bonus("solar_stack_damage_pct") * self._solar_stacks
            lunar_armor_pen = self._trait_bonus("lunar_stack_armor_pen_pct") * self._lunar_stacks
        # Demon Soul's execute_damage_pct (passive + Soul Projection's amplified delta) only
        # applies once the target's already below half HP, mirroring the existing beast_
        # damage_pct caller-side pattern above.
        sp = self._soul_projection_bonuses()
        if self.monster_hp > 0 and self.monster_hp < self.monster_max_hp * 0.5:
            damage_pct_bonus += bonuses.get("execute_damage_pct", 0) + sp.get("execute_damage_pct", 0)
        result = combat.resolve_attack(
            self._player_combat_stats(), self.monster.stats(), str_multiplier=str_multiplier, guaranteed_hit=guaranteed_hit,
            crit_chance_bonus=bonuses.get("crit_chance_pct", 0) + sp.get("crit_chance_pct", 0),
            crit_damage_bonus=bonuses.get("crit_damage_pct", 0) + sp.get("crit_damage_pct", 0),
            lifesteal_percent=bonuses.get("lifesteal_percent", 0) + sp.get("lifesteal_percent", 0),
            damage_pct_bonus=damage_pct_bonus,
            armor_penetration_pct=bonuses.get("armor_penetration_pct", 0) + sp.get("armor_penetration_pct", 0) + lunar_armor_pen,
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
            if label == "Attack":
                self._solar_stacks = min(5, self._solar_stacks + 1)
                self._lunar_stacks = min(5, self._lunar_stacks + 1)
            # Fire Dao Path: refreshes (doesn't stack) on every landed hit -- see
            # _apply_pending_burn_tick for where this actually deals damage, once per round.
            fire_burn_pct = bonuses.get("fire_burn_damage_pct", 0)
            if fire_burn_pct > 0 and self.monster_hp > 0:
                tick_damage = dao_paths.fire_burn_tick_damage(result.damage, fire_burn_pct)
                if tick_damage > 0:
                    self._burn_damage_per_tick = tick_damage
                    self._burn_ticks_remaining = dao_paths.FIRE_BURN_TICKS
                    self._log_line(f"🔥 Your flames catch hold of {self.monster.name}!")
            # Blazing Glory Sunfire Physique: same "refreshes, doesn't stack, on every landed
            # hit" shape as Fire Dao Path's burn above, but sized off the target's max HP
            # rather than this hit's damage -- a separate, independently-ticking burn source
            # (see _sunfire_burn_damage_per_tick/_apply_pending_sunfire_tick).
            sunfire_pct = self._trait_bonus("sunfire_burn_max_hp_pct")
            if sunfire_pct > 0 and self.monster_hp > 0:
                total_burn = round(self.monster_max_hp * sunfire_pct)
                tick_damage = max(1, round(total_burn / dao_paths.FIRE_BURN_TICKS))
                self._sunfire_burn_damage_per_tick = tick_damage
                self._sunfire_burn_ticks_remaining = dao_paths.FIRE_BURN_TICKS
                self._log_line(f"☀️ Sunfire catches hold of {self.monster.name}!")
            if freeze_chance and self.monster_hp > 0 and random.random() < freeze_chance:
                self.monster_frozen_rounds = max(self.monster_frozen_rounds, 1)
                self._log_line(f"❄️ {self.monster.name} is frozen solid and will miss its next attack!")
        if self.monster_hp <= 0:
            self._handle_victory()
        else:
            self._monster_turn()
        return result

    def _handle_victory(self):
        self.status = "victory"
        self._clear_active_hunt()
        # Forest Walker-family physique's "after winning a hunt, recover 3% max HP".
        post_hunt_heal_pct = self._trait_bonus("post_hunt_heal_pct")
        if post_hunt_heal_pct:
            healed = round(self.player_max_hp * post_hunt_heal_pct)
            self.player_hp = min(self.player_max_hp, self.player_hp + healed)
            self._persist_hp()
            if healed > 0:
                self._log_line(f"🌿 Your body recovers {healed} HP from the fight.")
        # Phoenix Feather-family physique: "defeating an enemy restores battle Qi".
        kill_qi_restore_pct = self._trait_bonus("kill_qi_restore_pct")
        if kill_qi_restore_pct:
            restored = round(self.player_max_qi * kill_qi_restore_pct)
            if restored > 0:
                self.player_qi = min(self.player_max_qi, self.player_qi + restored)
                self._persist_qi()
                self._log_line(f"🔥 Victory rekindles {restored} battle Qi.")
        bonuses = self._equipment_bonuses()
        loot_chance_multiplier = 1.0 + bonuses.get("loot_chance_bonus_pct", 0) + self.region_modifiers.get("loot_chance_bonus_pct", 0)
        beast_qty_bonus = self._trait_bonus("beast_material_quantity_bonus_pct")
        self.loot = roll_loot(self.monster, chance_multiplier=loot_chance_multiplier, beast_material_quantity_bonus_pct=beast_qty_bonus)
        effective_luck = self.player["luck_stat"] + bonuses["stats"]["luck_stat"]
        canon_drop = canon_gu.roll_canon_gu_drop(self.monster.gu_rank, "normal", luck_bonus=min(0.05, effective_luck * 0.001))
        if canon_drop:
            self.loot[canon_drop] = self.loot.get(canon_drop, 0) + 1
        # White Heaven's own 20 Rank 8 Unique Gu (see GameManager.roll_white_heaven_bonus_gu)
        # -- a completely separate 1/5000 roll, only ever eligible against a White Heaven
        # monster (detected via its own realm field, set on every White Heaven Monster
        # instance -- see content/monsters/white_heaven.py).
        if self.monster.realm == "White Heaven":
            bonus_gu = self.game.roll_white_heaven_bonus_gu()
            if bonus_gu:
                self.loot[bonus_gu] = self.loot.get(bonus_gu, 0) + 1
                self._log_line(f"🌟 A Rank 8 Unique Gu descends from White Heaven itself — **{bonus_gu}**!")
        essence_pill = roll_essence_restoration_pill_drop()
        if essence_pill:
            pill_name, pill_qty = essence_pill
            self.loot[pill_name] = self.loot.get(pill_name, 0) + pill_qty
            self._log_line(f"💧 You also find {pill_qty}x rare **{pill_name}**!")
        for item_name, quantity in self.loot.items():
            self.game.db.add_item(self.user_id, item_name, quantity)
        self._log_line(f"💥 {self.monster.name} is defeated!")
        hoard_reward = self.region_modifiers.get("hoard_reward")
        if hoard_reward:
            hoard_text = self.game.grant_reward(self.user_id, self.display_name, hoard_reward)
            self._log_line(f"🏆 Hoard guardian defeated — it was hiding {self.region_modifiers.get('hoard_label', 'a hoard')}: {hoard_text}!")
        granted = self.game.roll_and_grant_accessory_artifact(self.user_id, self.display_name, "hunt_kill", self.monster.gu_rank, [])
        if granted:
            self._log_line(f"✨ You also find **{granted['affix'].name}**!")
        # Spirit Severing Dao Marks (see GameManager.grant_dao_marks) -- silently a no-op for
        # anyone who hasn't reached Spirit Severing yet.
        self.game.grant_dao_marks(self.user_id, self.player)

    # -- action handlers -----------------------------------------------------

    def _track_battle_qi_spent(self, amount: float):
        """A Fire-family root's own "after spending 30% of your battle Qi in one encounter,
        +STR on your next attack" trigger (see character_data.CharacterTraitSpec) — counts
        every battle-Qi expenditure this encounter (Empower and Gu abilities alike), fires
        once per encounter the first time the running total crosses the threshold, and is
        consumed by the next _do_attack call regardless of whether that attack hits."""
        if not self.root_spec or self._fire_root_triggered or not self.root_spec.fire_battle_qi_trigger_fraction:
            return
        self._qi_spent_this_encounter += amount
        threshold = self.player_max_qi * self.root_spec.fire_battle_qi_trigger_fraction
        if self.player_max_qi > 0 and self._qi_spent_this_encounter >= threshold:
            self._fire_root_str_bonus_pending = True
            self._fire_root_triggered = True

    def _consume_empower(self) -> bool:
        """If Qi-empower is toggled on and affordable, spends it and returns True. Always
        clears the toggle. Thunder Muscle-family physique's "first Empower each encounter
        costs 2 less battle Qi" is applied before the affordability check, same "can help you
        afford it" convention Sturdy Frame's own first-Gu-use discount already uses."""
        cost = EMPOWER_QI_COST
        discount_pending = not self._first_empower_discounted
        if discount_pending:
            discount = self._trait_bonus("first_empower_discount_flat")
            if discount:
                cost = max(0, cost - discount)
        used = self.qi_empowered and self.player_qi >= cost
        if used:
            self.player_qi -= cost
            self._persist_qi()
            self._track_battle_qi_spent(cost)
            if discount_pending:
                self._first_empower_discounted = True
        self.qi_empowered = False
        return used

    async def _on_attack(self, interaction: discord.Interaction):
        def _resolve():
            empowered = self._consume_empower()
            if empowered:
                self._log_line("✨ You channel Qi to guarantee your strike!")
            self._do_attack(guaranteed_hit=empowered)

        await asyncio.to_thread(_resolve)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_observe(self, interaction: discord.Interaction):
        self._log_line("🔍 You study the beast's movements.")
        await asyncio.to_thread(self._monster_turn)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    def _apply_guard_or_potion_qi_restore(self):
        """River Walker-family physique's "Using Guard or a potion restores 3% of max battle
        Qi, once per encounter" — shared by _on_guard and the potion-use handler below."""
        if self._guard_or_potion_qi_restored:
            return
        restore_pct = self._trait_bonus("guard_or_potion_qi_restore_pct")
        if not restore_pct:
            return
        self._guard_or_potion_qi_restored = True
        restored = round(self.player_max_qi * restore_pct)
        if restored > 0:
            self.player_qi = min(self.player_max_qi, self.player_qi + restored)
            self._persist_qi()
            self._log_line(f"💧 Your physique restores {restored} battle Qi.")

    async def _on_guard(self, interaction: discord.Interaction):
        def _resolve():
            empowered = self._consume_empower()
            if empowered:
                self._log_line("✨ You channel Qi to fully brace against the blow!")
            else:
                self._log_line("🛡️ You brace for the next blow.")
            # Iron Skin-family physique's Guard stack (permanent for the rest of the
            # encounter — see _monster_turn) and River Walker-family physique's Guard/potion
            # Qi restore.
            self._guard_stacks = min(2, self._guard_stacks + 1)
            self._apply_guard_or_potion_qi_restore()
            self._monster_turn(incoming_reduction=1.0 if empowered else GUARD_DAMAGE_REDUCTION)

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
            chance = FLEE_BASE_CHANCE + (stats["spd_stat"] - self.monster.spd_stat) * FLEE_CHANCE_PER_SPD_DIFF
            chance += self._trait_bonus("flee_chance_flat")
            chance = max(MIN_FLEE_CHANCE, min(MAX_FLEE_CHANCE, chance))
            fled = random.random() < chance
            # Void-family physique: once per encounter, a failed flee gets one immediate
            # reroll at the same chance, before the monster's own punishing counter-attack —
            # the reroll itself is final either way, same "second result is final" convention
            # this session's other reroll mechanics already use.
            if not fled and not self._flee_reroll_used and self._trait_bonus("flee_reroll_once"):
                self._flee_reroll_used = True
                fled = random.random() < chance
                if fled:
                    self._log_line("🌀 Your physique bends space just enough for a second chance!")
            if fled:
                self.status = "fled"
                self._clear_active_hunt()
                self._log_line("🏃 You break away and escape the fight!")
                return False
            self._log_line("❌ You fail to escape!")
            self._monster_turn()
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
        # Sturdy Frame-family physique's "first Gu activation each encounter costs 1 less
        # Qi" — applied before the affordability check, so it can help you afford the ability.
        # Matches the pre-refactor behavior exactly: the flag is consumed here, before the
        # affordability check, not only on a successful cast.
        qi_cost = ability.qi_cost
        if not self._first_gu_use_discounted:
            discount = self._trait_bonus("first_gu_use_discount_flat")
            if discount:
                qi_cost = max(0, qi_cost - discount)
                self._first_gu_use_discounted = True
        if self.player_qi < qi_cost:
            await interaction.response.send_message(f"Not enough Qi to use {ability.name} (needs {qi_cost}).", ephemeral=True)
            return

        def _resolve():
            self.player_qi -= qi_cost
            self._persist_qi()
            self._track_battle_qi_spent(qi_cost)
            self._log_line(f"🐛 You channel {ability.name}!")
            result = self._do_attack(str_multiplier=ability.str_multiplier, label=ability.name, is_technique=True)
            # Moonlight-family physique: the first Gu ability that MISSES each encounter
            # refunds half its Qi cost — a miss here specifically means "didn't hit" (not a
            # dodge, which still counts as your Gu doing its job, just evaded).
            if result is not None and not result.hit and not self._gu_miss_refunded:
                refund_pct = self._trait_bonus("gu_miss_qi_refund_pct")
                if refund_pct:
                    self._gu_miss_refunded = True
                    refund = round(qi_cost * refund_pct)
                    if refund > 0:
                        self.player_qi = min(self.player_max_qi, self.player_qi + refund)
                        self._persist_qi()
                        self._log_line(f"🌙 The miss wasn't a total loss — {refund} Qi flows back to you.")

        await asyncio.to_thread(_resolve)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_killer_move(self, interaction: discord.Interaction):
        """Additive alongside _on_gu_ability above, not a replacement -- reads the separate
        equipped_combat_killer_move_id column (see GameManager.get_equipped_killer_move), spent
        from the same live self.player_qi tracking Empower/Gu-ability already use."""
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
            self._track_battle_qi_spent(qi_cost)
            self._log_line(f"🌀 You unleash {move['name']}!")
            if move["kind"] == "damage":
                self._do_attack(str_multiplier=move["effects"]["str_multiplier"], label=move["name"], is_technique=True)
            else:
                self.game.apply_killer_move_buff(self.user_id, self.player, move)
                self._log_line(f"✨ {move['name']} surges through you!")
                self._monster_turn()

        await asyncio.to_thread(_resolve)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_class_ability(self, interaction: discord.Interaction):
        class_name = self.player["character_class"]
        if class_name not in ("Tank", "Support", "Frostbinder"):
            await interaction.response.send_message(
                "You haven't chosen a class yet — run `/choose_class` to unlock a class ability.", ephemeral=True,
            )
            return

        def _resolve():
            if class_name == "Tank":
                self._log_line("🛡️ You brace with unshakable resolve — no ally around to protect but yourself!")
                self._monster_turn(incoming_reduction=BRACE_DAMAGE_REDUCTION)
            elif class_name == "Support":
                self.inspire_rounds_remaining = INSPIRE_DURATION_ROUNDS
                self._log_line("✨ You channel Inspire — your own STR and DEF surge!")
                self._monster_turn()
            else:
                self._log_line("❄️ You channel Freeze!")
                self._do_attack(str_multiplier=FREEZE_STR_MULTIPLIER, label="Freeze", freeze_chance=FREEZE_PROC_CHANCE, is_technique=True)

        await asyncio.to_thread(_resolve)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

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

        def _resolve():
            self.player_qi -= avatar.SOUL_PROJECTION_QI_COST
            self._persist_qi()
            self.soul_projection_rounds_remaining = avatar.soul_projection_duration(soul)
            self._log_line(f"🌀 You channel {avatar.SOUL_PROJECTION_NAME} — {soul.name}'s power surges through you!")
            self._do_attack(label=avatar.SOUL_PROJECTION_NAME, is_technique=True)

        await asyncio.to_thread(_resolve)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_change_gu(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 2)
        choice = select.values[0]
        if choice == "__unequip__":
            await asyncio.to_thread(self.game.unequip_item, self.user_id, self.display_name, "gu_ability")
        elif choice != "none":
            await asyncio.to_thread(self.game.equip_item, self.user_id, self.display_name, "gu_ability", choice)
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_use_potion(self, interaction: discord.Interaction):
        select = next(c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 4)
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
                self._log_line(f"🧪 You use {item_name} — {message}")
                self._apply_guard_or_potion_qi_restore()
                self._monster_turn()
            else:
                self._log_line(f"❌ Couldn't use {item_name}: {message}")

        await asyncio.to_thread(_resolve)
        self._finish_round()
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        if self.status == "fighting":
            self.status = "fled"
            await asyncio.to_thread(self._clear_active_hunt)
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
            ("Observe", "🔍", discord.ButtonStyle.success, self._on_observe),
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

        class_button = discord.ui.Button(
            label="Class Ability", emoji="🎭", style=discord.ButtonStyle.success, row=1, disabled=not active,
        )
        class_button.callback = self._on_class_ability
        self.add_item(class_button)

        equipped_gu_name = self.game.get_equipped(self.user_id).get("gu_ability")
        inventory = self.game.get_inventory(self.user_id)
        owned_gu = sorted(
            (name for name, item in EQUIPMENT.items() if item.slot_type == "Gu" and inventory.get(name, 0) > 0),
            key=lambda name: -gear_power_score(EQUIPMENT[name]),
        )
        gu_options = []
        if equipped_gu_name:
            gu_options.append(discord.SelectOption(label=f"Unequip {equipped_gu_name}", value="__unequip__", emoji="🗑️"))
        for name in owned_gu:
            gu_options.append(discord.SelectOption(label=name, value=name, description=EQUIPMENT[name].description[:100]))
        gu_select = discord.ui.Select(
            placeholder=f"Gu Ability: {equipped_gu_name}" if equipped_gu_name else "No Gu ability equipped",
            # Capped at Discord's 25-option limit on a Select — an active hunter can
            # realistically own more than 25 distinct Gu pieces.
            options=gu_options[:25] or [discord.SelectOption(label="None available", value="none")],
            disabled=not gu_options or not active,
            row=2,
        )
        gu_select.callback = self._on_change_gu
        self.add_item(gu_select)

        # Nascent Soul Avatar's Soul Projection (see avatar.py) -- this row used to be a
        # permanently-disabled "No realm ability unlocked" stub, scaffolded for exactly this.
        soul_projection_button = discord.ui.Button(
            label=f"Soul Projection ({avatar.SOUL_PROJECTION_QI_COST:,})", emoji="🌀",
            style=discord.ButtonStyle.success, row=3,
            disabled=not active or not self.player["avatar_soul"] or self.player_qi < avatar.SOUL_PROJECTION_QI_COST,
        )
        soul_projection_button.callback = self._on_soul_projection
        self.add_item(soul_projection_button)

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
            # Capped at Discord's 25-option limit — the tiered Alchemy pills alone can put a
            # player's usable Healing/Pills count well past that (see raid.py's potion
            # picker, which hit this exact ceiling before it was capped the same way).
            options=potion_options[:25] or [discord.SelectOption(label="None available", value="none")],
            disabled=not potion_options or cap_reached or not active,
            row=4,
        )
        potion_select.callback = self._on_use_potion
        self.add_item(potion_select)

    def build_embed(self) -> discord.Embed:
        m = self.monster
        monster_pct = int(100 * max(0, self.monster_hp) / self.monster_max_hp)
        player_pct = int(100 * max(0, self.player_hp) / self.player_max_hp)
        qi_pct = int(100 * max(0, self.player_qi) / max(1, self.player_max_qi))

        description = f"⚔️ Round **{self.round}** • {m.monster_type}"
        if self.inspire_rounds_remaining > 0:
            description += f"\n✨ **Inspire active** — your STR/DEF are boosted ({self.inspire_rounds_remaining} round(s) left)."
        embed = discord.Embed(
            title=f"⚔️ {m.name} Hunt • {STATUS_LABELS[self.status]}",
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
                f"🏔️ Realm {m.realm} • Status None\n"
                f"🎯 Next: **{m.ability.name}** — {m.ability.description}"
            ),
            inline=False,
        )

        equipped_gu_name = self.game.get_equipped(self.user_id).get("gu_ability")
        # Heavenly Sight Gu (see content/canon_gu_white_heaven.py) -- "reveals enemy stats,
        # hidden effects, traps, and weaknesses". A small, real presentation-only addition
        # rather than new combat math: shows the monster's own raw stat block and lifesteal
        # while equipped, same information a player could otherwise only infer from combat.
        # Equipped Gu names carry a "(Quality)" suffix -- parse_gu_name strips it to recover
        # the bare family name (see gu_types.gu_type_for's identical convention).
        equipped_gu_family = (parse_gu_name(equipped_gu_name)[0] or equipped_gu_name) if equipped_gu_name else None
        if equipped_gu_family == "Heavenly Sight Gu":
            heal_note = f" • 💉 Self-heals {m.ability.lifesteal_percent:.0%} of damage dealt" if m.ability.lifesteal_percent > 0 else ""
            embed.add_field(
                name="👁️ Heavenly Sight",
                value=(
                    f"🎯 ATK `{m.atk_stat:,}` ⚔️ STR `{m.str_stat:,}` 🛡️ DEF `{m.def_stat:,}`\n"
                    f"🏃 SPD `{m.spd_stat:,}` 🍀 LCK `{m.luck_stat:,}`{heal_note}"
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
                f"🐛 Gu Ability: {equipped_gu_name or 'None'} • Potions used: {self.potions_used}/{POTION_USE_CAP}{empower_note}"
            ),
            inline=False,
        )

        if self.log:
            embed.add_field(name="📜 Recent Combat", value="\n".join(self.log), inline=False)

        if self.status == "victory":
            loot_text = "\n".join(f"{name} x{qty}" for name, qty in self.loot.items()) or "Nothing this time."
            embed.add_field(name="🎁 Loot", value=loot_text, inline=False)
        elif self.status == "defeat":
            embed.add_field(
                name="💀 Outcome",
                value=f"You were beaten down and forced to retreat, losing **{self.qi_lost_on_death:,.2f} qi**. No loot.",
                inline=False,
            )
        elif self.status == "fled":
            embed.add_field(name="🏃 Outcome", value="You fled the fight. No loot.", inline=False)

        embed.set_footer(
            text=(
                f"Choose an action — go quiet for {HUNT_ROUND_TIMEOUT_SECONDS}s and you'll auto-attack "
                "on reflex instead."
            )
            if self.status == "fighting" else "This hunt has ended."
        )
        # The shared White Heaven image (see white_heaven_view.build_white_heaven_image_file)
        # is only physically ATTACHED once, at the initial send in cog.py -- but it stays on
        # the message across every subsequent edit that doesn't clear attachments (none of
        # this view's do), so every later embed just needs to keep pointing at that same
        # attachment to keep rendering it (mirrors InheritanceGroundBattleView.build_embed's
        # identical convention).
        if m.realm == "White Heaven" and os.path.exists(white_heaven.WHITE_HEAVEN_IMAGE_PATH):
            embed.set_image(url=f"attachment://{os.path.basename(white_heaven.WHITE_HEAVEN_IMAGE_PATH)}")
        return embed


class AbandonHuntView(GameView):
    """Self-service escape hatch attached to the "finish your current hunt first" refusal
    (see cog.py's /hunt command) -- mirrors raid.py's AbandonRaidView. A player's
    active_hunt_started_ts flag has no dependency on any specific HuntView instance still
    existing, so if their original hunt message scrolled away, got deleted, or a round-
    resolution error left the view unresponsive before HuntView.on_timeout/_clear_active_hunt
    ever got a chance to run, they'd otherwise be stuck until GameManager.
    ACTIVE_HUNT_STALE_SECONDS (2h) self-heals it with no way to act sooner."""

    def __init__(self, user_id: int, game):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.game = game
        button = discord.ui.Button(label="Abandon Stuck Hunt", emoji="🗑️", style=discord.ButtonStyle.danger)
        button.callback = self._on_abandon
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn't your hunt slot to clear.", ephemeral=True)
            return False
        return True

    async def _on_abandon(self, interaction: discord.Interaction):
        await asyncio.to_thread(self.game.abandon_active_hunt, self.user_id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="🗑️ Cleared — you can `/hunt` again now.", view=self)
