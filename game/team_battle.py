"""
Shared team-combat engine: multi-participant-vs-enemy round resolution (Attack, Guard,
Empower, Gu Ability, Class Ability, Killer Move, Soul Projection, Potion/Pill menu, full
physique/root trait stacking), extracted from raid.py so /raid and /inheritance_ground's
battle bubbles fight with byte-identical mechanics instead of a second, drift-prone
reimplementation. RaidView(TeamBattleEngine, GameView) and
InheritanceGroundView(TeamBattleEngine, GameView) both mix this in.

A concrete view must supply: self.game, self.enemies (list[RaidEnemy]), self.participants
(dict[user_id -> participant dict, see _build_participant_state]), self.actions (dict
collected for the round currently resolving), self.round (int), self.log (list[str]),
self.inspire_rounds_remaining (int). It must also define its own _on_victory()/_on_wipe()
(called once the fight ends either way) and _finish_round() (called by _submit_action once
every alive participant has locked in — resolves the round, rebuilds its own UI, refreshes
its own message, and restarts its own round timer if the fight is still ongoing; this stays
per-view rather than shared since raid's "status" state machine and inheritance ground's
"phase" state machine aren't the same shape).

Two hooks a concrete view MAY override (defaults are no-ops, matching /inheritance_ground's
narrower scope — no Flee, no telegraphed boss-charge special):
  _resolve_flee_phase()                                  -- RaidView overrides this.
  _maybe_handle_boss_charge(enemy, idx, alive_ids, defend_map) -- RaidView overrides this.
"""

import asyncio
import random

import discord

from . import avatar, chargen, combat, dao_paths
from .equipment import EQUIPMENT
from .items import ITEMS
from .base_view import GameView

GUARD_DAMAGE_REDUCTION = 0.5
EMPOWER_QI_COST = 15
POTION_USE_CAP = 3
MAX_LOG_LINES = 8

# Class Ability (see character_class.py) — one team-battle-only ability per class,
# dispatched off the clicking player's character_class:
#   Tank's Defend Ally        -> redirects an ally's incoming hits onto the Tank this round.
#   Support's Inspire         -> buffs the whole party's STR/DEF for a few rounds.
#   Frostbinder's Freeze      -> a weaker attack with a chance to skip the target's next hit.
DEFEND_ALLY_DAMAGE_REDUCTION = 0.25
INSPIRE_STR_BONUS_PCT = 0.15
INSPIRE_DEF_BONUS_PCT = 0.15
INSPIRE_DURATION_ROUNDS = 3  # includes the round Inspire is cast in
FREEZE_STR_MULTIPLIER = 0.8
FREEZE_PROC_CHANCE = 0.5

# Blood Sea Ancestor's Inheritance Ground monster pool (see content/monsters/
# blood_sea_ancestor.py, monsters.py's own added MonsterAbility/Monster fields) -- shared
# tuning constants for the mechanics those monsters use.
BLEED_TICKS = 3  # matches dao_paths.FIRE_BURN_TICKS's own convention
# Blood Gu Abomination (monsters.Monster.random_blood_gu) re-picks one of these three modes,
# at these fixed magnitudes, on every one of its own attacks instead of using a fixed ability.
RANDOM_BLOOD_GU_EXECUTE_PCT = 0.30
RANDOM_BLOOD_GU_BLEED_PCT = 0.15
RANDOM_BLOOD_GU_DEBUFF_SPD_PCT = 0.30
RANDOM_BLOOD_GU_DEBUFF_DODGE_PCT = 0.40


class RaidEnemy:
    def __init__(self, monster):
        self.monster = monster
        self.hp = monster.hp
        self.max_hp = monster.hp
        self.frozen_rounds = 0  # Frostbinder's Freeze — >0 means this enemy skips its next attack
        # Fire Dao Path burn (see dao_paths.fire_burn_tick_damage) -- seeded on a landed hit
        # from ANY Fire-path participant, ticks once per round in _resolve_round regardless of
        # whose turn queued the round.
        self.burn_damage_per_tick = 0
        self.burn_ticks_remaining = 0
        # Blazing Glory Sunfire Physique -- an independent second burn source, same "refreshes,
        # doesn't stack" shape as Fire Dao Path's above, ticked alongside it in Phase 1.5.
        self.sunfire_burn_damage_per_tick = 0
        self.sunfire_burn_ticks_remaining = 0
        # Blood Fang Wolf-style enrage (monster.enrage_atk_pct_per_stack/enrage_stack_cap) --
        # grows whenever EITHER side loses HP to this specific enemy (see Phase 1 and
        # _resolve_enemy_hit), boosts this enemy's own str_multiplier in Phase 3.
        self.enrage_stacks = 0
        # Blood River Python-style submerge (monster.submerge_every_rounds/
        # submerge_duration_rounds) -- ticked once per round at the very top of _resolve_round
        # (see _tick_submerge), read by Phase 1 to skip player attacks against this enemy
        # while submerged.
        self.submerge_round_counter = 0
        self.submerged_rounds_remaining = 0
        # DPS-check timer (monster.dps_check_first_turn/dps_check_interval_growth -- see
        # Blood Sea Demon Disciple / Blood Sea Ancestor's Blood Will) -- dps_check_interval
        # is the CURRENT gap being counted down, growing by dps_check_interval_growth after
        # each forced kill; dps_check_next_kill_round is the absolute round number the next
        # kill fires on. Both stay at their initial values (irrelevant) if the mechanic is off.
        self.dps_check_interval = monster.dps_check_first_turn
        self.dps_check_next_kill_round = monster.dps_check_first_turn

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def stats(self) -> dict:
        return self.monster.stats()


class TeamBattleEngine:
    """Mixin -- never instantiated directly, has no __init__ of its own (relies on the
    concrete view's own __init__/GameView.__init__ via normal MRO)."""

    # -- helpers -------------------------------------------------------------------------

    def _alive_enemies(self):
        return [e for e in self.enemies if e.alive]

    def _alive_participant_ids(self):
        return [uid for uid, p in self.participants.items() if not p["down"]]

    def _log(self, text: str):
        self.log.append(text)
        self.log = self.log[-MAX_LOG_LINES:]

    def _persist_hp(self, user_id: int, p: dict):
        """Writes p["hp"] back to the DB — minus hp_bonus, since the stored hp/max_hp columns
        stay gear-independent (db.set_hp's own clamp is against the un-bonused max_hp, so
        persisting the inflated number would just get silently cut back down)."""
        self.game.db.set_hp(user_id, max(1, p["hp"] - p.get("hp_bonus", 0)))

    def _persist_qi(self, user_id: int, p: dict):
        """Writes p["qi"] back to the DB — minus qi_bonus, mirroring _persist_hp
        (db.set_battle_qi's own clamp is against the un-bonused qi_stat column, so
        persisting the inflated number would just get silently cut back down)."""
        self.game.db.set_battle_qi(user_id, max(0.0, p["qi"] - p.get("qi_bonus", 0)))

    def _try_negate_fatal_hit(self, user_id: int, p: dict) -> bool:
        """Mythic Physique's "ignore the first fatal hit each day" — True (and consumes the
        day's charge) only for a Mythic-physique participant who hasn't already used it today."""
        if p.get("physique_tier") != "Mythic":
            return False
        return self.game.db.try_use_daily_fatal_hit_negation(user_id)

    def _try_avatar_fatal_block(self, user_id: int, p: dict) -> bool:
        """Nascent Soul Avatar's own once-daily fatal-blow shield — independent of Mythic
        Physique's charge above (a participant with both gets two separate saves), gated
        only on having chosen an avatar soul at all, not on level or which soul."""
        if not p.get("avatar_soul"):
            return False
        return self.game.db.try_use_daily_avatar_fatal_block(user_id)

    def _soul_projection_bonuses(self, user_id: int, p: dict) -> dict:
        """Extra amounts Soul Projection adds on top of the passive while active this round
        for THIS participant — empty when inactive or no soul chosen. Keyed the same as
        compute_equipment_bonuses' special dict for the keys the attack/defense resolve_attack
        calls read; Formation Soul's flat STR/DEF and Demon Soul's low_hp_atk_bonus are
        consumed directly in _attacker_stats instead."""
        if p.get("soul_projection_rounds_remaining", 0) <= 0:
            return {}
        soul_name = p.get("avatar_soul")
        soul = avatar.get_avatar_soul(soul_name)
        if soul is None:
            return {}
        multiplier = self.game.soul_projection_multiplier(user_id)
        return {
            key: avatar.soul_projection_bonus(soul_name, p.get("avatar_level", 1), key, multiplier)
            for key in avatar.SOUL_PROJECTION_KEYS.get(soul.name, ())
        }

    def _equipped_gu(self, user_id: int):
        gu_name = self.game.get_equipped(user_id).get("gu_ability")
        return EQUIPMENT.get(gu_name) if gu_name else None

    def _trait_bonus(self, p: dict, key: str) -> float:
        """A participant's named root AND named physique own stat_bonuses value for `key`
        (see character_data.CharacterTraitSpec), summed — mirrors hunt.py's identical helper,
        just reading off the participant dict instead of self."""
        root_spec = chargen.get_root_spec(p.get("root_name"))
        physique_spec = chargen.get_physique_spec(p.get("physique_name"))
        root_value = root_spec.stat_bonuses.get(key, 0) if root_spec else 0
        physique_value = physique_spec.stat_bonuses.get(key, 0) if physique_spec else 0
        return root_value + physique_value

    def _attacker_stats(self, user_id: int, p: dict) -> tuple:
        """Returns (stats, bonuses, soul_projection_bonuses) — the third element is computed
        here (needed for the flat-stat fold-in below) and handed back so callers don't have
        to re-derive it (soul_projection_multiplier does real DB reads)."""
        bonuses = self.game.compute_equipment_bonuses(user_id)
        stats_bonus = bonuses["stats"]
        player = self.game.get_player_stats(user_id, p["name"])
        stats = {
            "atk_stat": player["atk_stat"] + stats_bonus["atk_stat"],
            "str_stat": player["str_stat"] + stats_bonus["str_stat"],
            "def_stat": player["def_stat"] + stats_bonus["def_stat"],
            "spd_stat": player["spd_stat"] + stats_bonus["spd_stat"],
            "luck_stat": player["luck_stat"] + stats_bonus["luck_stat"],
        }
        if self.inspire_rounds_remaining > 0:
            stats["str_stat"] = round(stats["str_stat"] * (1 + INSPIRE_STR_BONUS_PCT))
            stats["def_stat"] = round(stats["def_stat"] * (1 + INSPIRE_DEF_BONUS_PCT))
        # Formation Soul's REAL passive (see avatar.py) -- every OTHER alive same-sect
        # participant with Formation Soul buffs THIS participant's STR/DEF, always on (no
        # Soul Projection needed). Pure in-memory scan against each participant's own cached
        # sect_id/avatar_soul, no DB calls. Never buffs the Formation Soul holder themselves
        # this way -- "sect members fighting ALONGSIDE you," matching the soul's own passive_text.
        sect_id = p.get("sect_id")
        if sect_id:
            for other_id, other in self.participants.items():
                if other_id == user_id or other.get("down") or other.get("sect_id") != sect_id:
                    continue
                if other.get("avatar_soul") != "Formation Soul":
                    continue
                str_bonus = avatar.scaled_bonus(other["avatar_soul"], other.get("avatar_level", 1), "sect_buff_str_pct")
                def_bonus = avatar.scaled_bonus(other["avatar_soul"], other.get("avatar_level", 1), "sect_buff_def_pct")
                if str_bonus:
                    stats["str_stat"] = round(stats["str_stat"] * (1 + str_bonus))
                if def_bonus:
                    stats["def_stat"] = round(stats["def_stat"] * (1 + def_bonus))
        # Heavenly Solar Physique -- every OTHER alive participant (no sect gate, unlike
        # Formation Soul above -- "every friendly character" per explicit request) with this
        # physique buffs THIS participant's DEF, always on. Same self-exclusion as Formation
        # Soul: the holder buffs allies fighting alongside them, not themselves this way.
        for other_id, other in self.participants.items():
            if other_id == user_id or other.get("down"):
                continue
            def_aura_pct = chargen.get_physique_spec(other.get("physique_name"))
            def_aura_pct = def_aura_pct.stat_bonuses.get("ally_def_aura_pct", 0) if def_aura_pct else 0
            if def_aura_pct:
                stats["def_stat"] = round(stats["def_stat"] * (1 + def_aura_pct))
        # Soul Projection (see avatar.py): Formation Soul's ACTIVE version buffs the caster's
        # own STR/DEF (their ally-targeted passive is the scan just above); Demon Soul's
        # amplified low_hp_atk_bonus folds into the SAME below-50%-HP-gated flat bonus the
        # passive version already uses, just below, rather than a separate ungated add.
        sp = self._soul_projection_bonuses(user_id, p)
        if sp.get("sect_buff_str_pct"):
            stats["str_stat"] = round(stats["str_stat"] * (1 + sp["sect_buff_str_pct"]))
        if sp.get("sect_buff_def_pct"):
            stats["def_stat"] = round(stats["def_stat"] * (1 + sp["sect_buff_def_pct"]))
        low_hp_bonus = bonuses.get("low_hp_atk_bonus", 0) + sp.get("low_hp_atk_bonus", 0)
        if low_hp_bonus and 0 < p["hp"] < p["max_hp"] * 0.5:
            stats["str_stat"] += low_hp_bonus
        # Phoenix Feather-family physique: the same "below 50% HP" threshold, but a % bonus.
        low_hp_str_pct = self.game._trait_bonus(player, "low_hp_str_pct_bonus")
        if low_hp_str_pct and 0 < p["hp"] < p["max_hp"] * 0.5:
            stats["str_stat"] = round(stats["str_stat"] * (1 + low_hp_str_pct))
        # Clear Mind-family physique's encounter-start adaptive stat (see _build_participant_state).
        adaptive_key = p.get("adaptive_stat_key")
        if adaptive_key:
            stats[adaptive_key] = round(stats[adaptive_key] * (1 + self.game._trait_bonus(player, "encounter_start_adaptive_stat_pct")))
        return stats, bonuses, sp

    def _resolve_target_index(self, p: dict) -> int:
        """The enemy index a player's next action should hit — their preferred target if
        it's still alive, otherwise the first alive enemy. -1 if nothing's left standing."""
        alive = self._alive_enemies()
        if not alive:
            return -1
        idx = p.get("target_index", 0)
        if idx >= len(self.enemies) or not self.enemies[idx].alive:
            idx = self.enemies.index(alive[0])
        return idx

    def _build_participant_state(self, user_id: int, name: str, player: dict) -> dict:
        """The full per-encounter combat-state dict for one participant (equipment overlay,
        per-encounter physique/root state, etc.) — shared by RaidView._add_participant (which
        layers raid-only loot/region fields on top before inserting) and
        InheritanceGroundView._start_battle (which inserts this as-is). Sync — callers
        dispatch via asyncio.to_thread themselves."""
        # Equipped gear's flat "hp"/"qi_stat" stat_bonuses are folded in as a live overlay
        # on top of the persisted (gear-independent) hp/max_hp and battle_qi/qi_stat
        # columns, same as atk/str/def/spd/luck already work — see _persist_hp/_persist_qi
        # for why writes back to the DB subtract them back out again.
        equip_bonuses = self.game.compute_equipment_bonuses(user_id)["stats"]
        hp_bonus = equip_bonuses["hp"]
        qi_bonus = equip_bonuses["qi_stat"]
        hp_settled = self.game.db.settle_hp_regen(user_id)
        # Sturdy Frame-family physique's battle_qi_regen_bonus_pct — same rate-multiplier
        # hunt.py's own settle_battle_qi call applies.
        regen_bonus = self.game._trait_bonus(player, "battle_qi_regen_bonus_pct")
        qi_settled = self.game.db.settle_battle_qi(user_id, regen_rate_bonus_pct=regen_bonus)
        alive = self._alive_enemies()
        default_target = self.enemies.index(alive[0]) if alive else 0
        state = {
            "name": name, "hp": hp_settled["hp"] + hp_bonus, "max_hp": hp_settled["max_hp"] + hp_bonus, "down": False,
            "qi": qi_settled["battle_qi"] + qi_bonus, "max_qi": qi_settled["qi_stat"] + qi_bonus, "empowered": False,
            "target_index": default_target, "potions_used": 0,
            "character_class": player["character_class"], "hp_bonus": hp_bonus, "qi_bonus": qi_bonus,
            "race": player["race"], "physique_tier": player["physique_tier"],
            # A Fire-family root's "spend 30% of your battle Qi this encounter" trigger (see
            # character_data.CharacterTraitSpec / hunt.py's identical _track_battle_qi_spent)
            # -- tracked per-participant since several people spend Qi at once here.
            "root_name": player["root_name"], "qi_spent": 0.0, "fire_str_pending": False, "fire_triggered": False,
            # Common-tier physique combat state (see character_data.py's Common physique
            # section / hunt.py's identical per-participant fields) — also per-participant.
            "physique_name": player["physique_name"], "guard_stacks": 0,
            "dodge_momentum_pending": False, "dodge_momentum_triggered": False, "attack_count": 0,
            "first_gu_use_discounted": False, "guard_or_potion_qi_restored": False,
            "damage_dealt": 0.0, "adaptive_stat_key": None,
            # Uncommon/Rare-tier physique combat state (see character_data.py for the families).
            "first_empower_discounted": False, "flee_reroll_used": False, "gu_miss_refunded": False,
            # Nascent Soul Avatar (see avatar.py) — avatar_soul/avatar_level needed for both
            # Soul Projection and the passive fold-in inside _attacker_stats; sect_id for
            # Formation Soul's real ally-targeted buff (pure in-memory scan against every
            # other participant's own cached sect_id, no per-round DB calls).
            "avatar_soul": player["avatar_soul"], "avatar_level": player["avatar_level"], "sect_id": player["sect_id"],
            "soul_projection_rounds_remaining": 0,
            # Bloodscale Serpent-style Bleed (see Phase 1.65 / _resolve_enemy_hit) -- seeded on
            # a landed enemy hit, ticked once per round independent of who queued the round.
            "bleed_damage_per_tick": 0, "bleed_ticks_remaining": 0,
        }
        # Clear Mind-family physique's encounter-start adaptive stat — compared against the
        # opponent (self.enemies[0]), same one-time-at-join computation hunt.py's own
        # single-monster version uses.
        physique_spec = chargen.get_physique_spec(player["physique_name"])
        if physique_spec and physique_spec.stat_bonuses.get("encounter_start_adaptive_stat_pct") and self.enemies:
            boss = self.enemies[0].monster
            ratios = {
                "atk_stat": player["atk_stat"] / max(1, boss.atk_stat),
                "def_stat": player["def_stat"] / max(1, boss.def_stat),
                "spd_stat": player["spd_stat"] / max(1, boss.spd_stat),
            }
            state["adaptive_stat_key"] = min(ratios, key=ratios.get)
        return state

    def _validate_actor(self, user_id: int):
        """Returns (participant, error_message_or_None). Concrete views may add their own
        earlier checks (e.g. RaidView's "hasn't started"/"already ended" status gates) before
        delegating to this for the shared "not joined"/"knocked out"/"already acted" checks."""
        p = self.participants.get(user_id)
        if p is None:
            return None, "Join the fight before acting!"
        if p["down"]:
            return None, "You've been knocked out and can't act for the rest of this fight."
        if user_id in self.actions:
            return None, "You've already locked in your action for this round — wait for it to resolve."
        return p, None

    async def _submit_action(self, user_id: int, action: dict):
        self.actions[user_id] = action
        if self._alive_participant_ids() and set(self._alive_participant_ids()).issubset(self.actions.keys()):
            await self._finish_round()
        else:
            await asyncio.to_thread(self._build_components)
            await self._refresh_message()

    async def _refresh_message(self):
        if self.message is not None:
            try:
                embed = await asyncio.to_thread(self.build_embed)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    def _track_battle_qi_spent(self, p: dict, amount: float):
        """Mirrors hunt.py's _track_battle_qi_spent — see _build_participant_state's own
        comment for why this state lives per-participant here instead of on self. Reads via
        .get() throughout (not p[...]) so a participant dict from anywhere that predates
        these keys just behaves as "no root, never triggers" instead of a hard KeyError."""
        root_spec = chargen.get_root_spec(p.get("root_name"))
        if not root_spec or p.get("fire_triggered") or not root_spec.fire_battle_qi_trigger_fraction:
            return
        p["qi_spent"] = p.get("qi_spent", 0.0) + amount
        max_qi = p.get("max_qi", 0)
        threshold = max_qi * root_spec.fire_battle_qi_trigger_fraction
        if max_qi > 0 and p["qi_spent"] >= threshold:
            p["fire_str_pending"] = True
            p["fire_triggered"] = True

    def _consume_empower_cost(self, user_id: int, p: dict) -> bool:
        """If Empower is toggled on and affordable, spends it and returns True — shared by
        _on_attack and _on_guard. Thunder Muscle-family physique's "first Empower each
        encounter costs 2 less battle Qi" is applied before the affordability check, same
        "can help you afford it" convention hunt.py's identical _consume_empower uses."""
        cost = EMPOWER_QI_COST
        discount_pending = not p.get("first_empower_discounted")
        if discount_pending:
            discount = self._trait_bonus(p, "first_empower_discount_flat")
            if discount:
                cost = max(0, cost - discount)
        empowered = p["empowered"] and p["qi"] >= cost
        if empowered:
            p["qi"] -= cost
            self._persist_qi(user_id, p)
            self._track_battle_qi_spent(p, cost)
            if discount_pending:
                p["first_empower_discounted"] = True
        return empowered

    def _apply_guard_or_potion_qi_restore(self, user_id: int, p: dict):
        """River Walker-family physique's "Using Guard or a potion restores 3% of max battle
        Qi, once per encounter" — mirrors hunt.py's identical helper."""
        if p.get("guard_or_potion_qi_restored"):
            return
        restore_pct = self._trait_bonus(p, "guard_or_potion_qi_restore_pct")
        if not restore_pct:
            return
        p["guard_or_potion_qi_restored"] = True
        restored = round(p["max_qi"] * restore_pct)
        if restored > 0:
            p["qi"] = min(p["max_qi"], p["qi"] + restored)
            self._persist_qi(user_id, p)
            self._log(f"💧 **{p['name']}**'s physique restores {restored} battle Qi.")

    # -- optional hooks (defaults = /inheritance_ground's narrower scope) -----------------

    def _resolve_flee_phase(self):
        """RaidView overrides this with its real Phase 2 flee logic. No-op by default (no
        Flee action is offered outside /raid)."""
        return

    def _maybe_handle_boss_charge(self, enemy: "RaidEnemy", idx: int, alive_ids: list, defend_map: dict) -> bool:
        """RaidView overrides this with its main-boss telegraphed-nuke special. Returns
        False by default (no charge mechanic outside /raid) — the enemy just attacks normally."""
        return False

    # -- round resolution -----------------------------------------------------------------

    def _tick_submerge(self):
        """Advances every alive enemy's submerge cycle (monster.submerge_every_rounds/
        submerge_duration_rounds -- see Blood River Python) BEFORE Phase 1 resolves this
        round's player attacks, so a fresh submerge takes effect the same round it triggers."""
        for enemy in self.enemies:
            if not enemy.alive or not enemy.monster.submerge_every_rounds:
                continue
            if enemy.submerged_rounds_remaining > 0:
                enemy.submerged_rounds_remaining -= 1
                continue
            enemy.submerge_round_counter += 1
            if enemy.submerge_round_counter >= enemy.monster.submerge_every_rounds:
                enemy.submerge_round_counter = 0
                enemy.submerged_rounds_remaining = enemy.monster.submerge_duration_rounds
                self._log(f"🌊 {enemy.monster.name} submerges beneath the blood pool — untargetable!")

    def _resolve_round(self):
        self._tick_submerge()

        # Phase 0: Support's Inspire — resolved before damage so this round's own attacks
        # already benefit. Doesn't stack in magnitude (multiple Supports just refresh the
        # same duration), and costs the caster their attack that round.
        for user_id, action in self.actions.items():
            if action["type"] != "inspire":
                continue
            p = self.participants.get(user_id)
            if p is None or p["down"]:
                continue
            self.inspire_rounds_remaining = INSPIRE_DURATION_ROUNDS
            self._log(f"✨ **{p['name']}** inspires the party — STR and DEF surge!")

        # Phase 0.5: Soul Projection (see avatar.py) — same "resolve before damage so this
        # round's own attacks already benefit" placement as Inspire above, but PER-
        # PARTICIPANT (unlike Inspire's single shared flag) since souls differ per player.
        for user_id, action in self.actions.items():
            if action["type"] != "soul_projection":
                continue
            p = self.participants.get(user_id)
            if p is None or p["down"]:
                continue
            soul = avatar.get_avatar_soul(p.get("avatar_soul"))
            if soul is None:
                continue
            p["soul_projection_rounds_remaining"] = avatar.soul_projection_duration(soul)
            self._log(f"🌀 **{p['name']}** channels {avatar.SOUL_PROJECTION_NAME} — {soul.name}'s power surges through them!")

        # Phase 1: player attacks / Gu abilities / Freeze / Soul Projection / damage-kind
        # Killer Moves, in submission order.
        for user_id, action in list(self.actions.items()):
            p = self.participants.get(user_id)
            if p is None or p["down"] or action["type"] not in ("attack", "gu", "freeze", "soul_projection", "killer_move"):
                continue
            alive = self._alive_enemies()
            if not alive:
                break
            target_idx = action["target"]
            if target_idx < 0 or target_idx >= len(self.enemies) or not self.enemies[target_idx].alive:
                target = alive[0]
            else:
                target = self.enemies[target_idx]

            attacker_stats, bonuses, sp = self._attacker_stats(user_id, p)
            is_gu = action["type"] == "gu"
            is_freeze = action["type"] == "freeze"
            is_soul_projection = action["type"] == "soul_projection"
            is_killer_move = action["type"] == "killer_move"
            if is_gu:
                str_multiplier = action["ability"].str_multiplier
                label = action["ability"].name
            elif is_freeze:
                str_multiplier = FREEZE_STR_MULTIPLIER
                label = "Freeze"
            elif is_soul_projection:
                # Struck with the buff this SAME action just activated (Phase 0.5 already
                # set p["soul_projection_rounds_remaining"] above, so _attacker_stats' own sp
                # read here already reflects it) -- not a toggle-then-attack like Empower,
                # the projection itself IS the attack.
                str_multiplier = 1.0
                label = avatar.SOUL_PROJECTION_NAME
            elif is_killer_move:
                str_multiplier = action["move"]["effects"]["str_multiplier"]
                label = action["move"]["name"]
            else:
                str_multiplier = 1.0
                label = "Attack"
            # Gu abilities / Freeze / Soul Projection / Killer Moves count as "technique"
            # damage; a plain Attack is "physical" — see manual_view.EFFECT_LABELS'
            # technique_damage_pct/physical_damage_pct.
            base_damage_pct_bonus = (bonuses.get("technique_damage_pct", 0) if (is_gu or is_freeze or is_soul_projection or is_killer_move) else bonuses.get("physical_damage_pct", 0)) + bonuses.get("total_damage_pct", 0)
            # A Lightning-family root's empower_damage_pct (only on an actually-Empowered
            # attack) and a Fire-family root's battle-Qi trigger (consumed on whichever
            # attack comes next, hit or miss — see _track_battle_qi_spent) — mirrors hunt.py's
            # identical _do_attack handling.
            root_spec = chargen.get_root_spec(p.get("root_name"))
            if action.get("guaranteed"):
                base_damage_pct_bonus += self._trait_bonus(p, "empower_damage_pct")
            if p.get("fire_str_pending"):
                base_damage_pct_bonus += root_spec.fire_battle_qi_str_bonus_pct
                p["fire_str_pending"] = False
            # Swift Foot-family physique's Momentum (consumed on whichever basic Attack comes
            # next, hit or miss) and Strong Bone-family physique's every-3rd-basic-Attack
            # bonus — both "basic Attack" only, mirrors hunt.py's identical _do_attack.
            lunar_armor_pen = 0.0
            if label == "Attack":
                if p.get("dodge_momentum_pending"):
                    base_damage_pct_bonus += self._trait_bonus(p, "dodge_momentum_str_bonus_pct")
                    p["dodge_momentum_pending"] = False
                p["attack_count"] = p.get("attack_count", 0) + 1
                if p["attack_count"] % 3 == 0:
                    base_damage_pct_bonus += self._trait_bonus(p, "every_third_attack_bonus_pct")
                # Heavenly Solar/Lunar Physique -- both read the stack count BEFORE this
                # attack (grown by prior landed basic Attacks), same "read old count,
                # increment after a landed hit" order Iron Skin's own guard_stacks uses.
                base_damage_pct_bonus += self._trait_bonus(p, "solar_stack_damage_pct") * p.get("solar_stacks", 0)
                lunar_armor_pen = self._trait_bonus(p, "lunar_stack_armor_pen_pct") * p.get("lunar_stacks", 0)
            # Heavenly Lunar Physique -- basic Attacks hit EVERY alive enemy instead of just
            # the chosen one, per explicit request. Snapshotted once per action so a kill
            # mid-volley doesn't retroactively shrink who else gets hit; each target still
            # gets its own independent hit/dodge/crit roll and damage number below (a real
            # AOE cleave, not one roll copied to every enemy).
            if label == "Attack" and self._trait_bonus(p, "lunar_aoe_attacks"):
                attack_targets = list(alive)
            else:
                attack_targets = [target]
            any_hit_landed = False
            for target in attack_targets:
                if not target.alive:
                    continue
                # Blood River Python-style submerge (see _tick_submerge) -- untargetable while
                # submerged, the attack simply finds nothing (no roll, no cost refund logic
                # beyond what a normal miss already grants).
                if target.submerged_rounds_remaining > 0:
                    self._log(f"🌊 **{p['name']}**'s {label} finds nothing — {target.monster.name} is submerged!")
                    continue
                damage_pct_bonus = base_damage_pct_bonus
                # A Strength-family root's beast_damage_pct only applies against Beast-type
                # enemies — the offensive counterpart to Gu's existing beast_damage_reduction_pct.
                if target.monster.monster_type == "Beast":
                    damage_pct_bonus += self._trait_bonus(p, "beast_damage_pct")
                # Demon Soul's execute_damage_pct (passive + Soul Projection's amplified delta)
                # only applies once the target's already below half HP, mirroring hunt.py's
                # identical caller-side pattern.
                if target.hp > 0 and target.hp < target.max_hp * 0.5:
                    damage_pct_bonus += bonuses.get("execute_damage_pct", 0) + sp.get("execute_damage_pct", 0)
                # Crimson Formation Guardian-style shield -- damage taken is reduced while any
                # OTHER enemy in this same fight is still alive (see monsters.Monster.
                # shield_while_ally_alive_pct); encoded as a negative damage_pct_bonus since
                # resolve_attack's own incoming_reduction is the DEFENDER's kwarg, not
                # available from the attacker's own call here.
                if target.monster.shield_while_ally_alive_pct > 0 and any(other is not target and other.alive for other in self.enemies):
                    damage_pct_bonus -= target.monster.shield_while_ally_alive_pct
                result = combat.resolve_attack(
                    attacker_stats, target.stats(), str_multiplier=str_multiplier,
                    guaranteed_hit=action.get("guaranteed", False),
                    crit_chance_bonus=bonuses.get("crit_chance_pct", 0) + sp.get("crit_chance_pct", 0),
                    crit_damage_bonus=bonuses.get("crit_damage_pct", 0) + sp.get("crit_damage_pct", 0),
                    lifesteal_percent=bonuses.get("lifesteal_percent", 0) + sp.get("lifesteal_percent", 0),
                    damage_pct_bonus=damage_pct_bonus,
                    armor_penetration_pct=bonuses.get("armor_penetration_pct", 0) + sp.get("armor_penetration_pct", 0) + lunar_armor_pen,
                    max_dodge_chance=combat.MONSTER_MAX_DODGE_CHANCE,
                )
                if not result.hit:
                    self._log(f"❌ **{p['name']}** uses {label} on {target.monster.name} but misses!")
                    # Moonlight-family physique: the first Gu ability that misses each encounter
                    # refunds half its Qi cost — mirrors hunt.py's identical _on_gu_ability handling.
                    if is_gu and not p.get("gu_miss_refunded"):
                        refund_pct = self._trait_bonus(p, "gu_miss_qi_refund_pct")
                        if refund_pct:
                            p["gu_miss_refunded"] = True
                            refund = round(action["ability"].qi_cost * refund_pct)
                            if refund > 0:
                                p["qi"] = min(p["max_qi"], p["qi"] + refund)
                                self._persist_qi(user_id, p)
                                self._log(f"🌙 **{p['name']}**'s miss wasn't a total loss — {refund} Qi flows back.")
                elif result.dodged:
                    self._log(f"💨 {target.monster.name} dodges **{p['name']}**'s {label}!")
                else:
                    any_hit_landed = True
                    target.hp = max(0, target.hp - result.damage)
                    # Blood Fang Wolf-style enrage -- grows whenever EITHER side loses HP to
                    # this enemy (see _resolve_enemy_hit for the other direction).
                    if target.monster.enrage_stack_cap > 0:
                        target.enrage_stacks = min(target.monster.enrage_stack_cap, target.enrage_stacks + 1)
                    # Paradise Earth Inheritor Root's Merit needs to know who DIDN'T deal the
                    # most damage this raid — see RaidView._on_victory.
                    p["damage_dealt"] = p.get("damage_dealt", 0) + result.damage
                    crit = " (Critical!)" if result.crit else ""
                    heal_text = ""
                    if result.heal:
                        p["hp"] = min(p["max_hp"], p["hp"] + result.heal)
                        self._persist_hp(user_id, p)
                        heal_text = f" 💚 +{result.heal} HP"
                    self._log(f"⚔️ **{p['name']}** hits {target.monster.name} for {result.damage} damage{crit}.{heal_text}")
                    # Fire Dao Path: refreshes (doesn't stack) on every landed hit from ANY
                    # Fire-path participant -- see the Phase 1.5 tick loop below for where this
                    # actually deals damage, once per round.
                    fire_burn_pct = bonuses.get("fire_burn_damage_pct", 0)
                    if fire_burn_pct > 0 and target.hp > 0:
                        tick_damage = dao_paths.fire_burn_tick_damage(result.damage, fire_burn_pct)
                        if tick_damage > 0:
                            target.burn_damage_per_tick = tick_damage
                            target.burn_ticks_remaining = dao_paths.FIRE_BURN_TICKS
                            self._log(f"🔥 **{p['name']}**'s flames catch hold of {target.monster.name}!")
                    # Blazing Glory Sunfire Physique: same "refreshes, doesn't stack" shape as Fire
                    # Dao Path's burn above, but sized off the target's max HP rather than this
                    # hit's damage -- a separate, independently-ticking burn source (Phase 1.5).
                    sunfire_pct = self._trait_bonus(p, "sunfire_burn_max_hp_pct")
                    if sunfire_pct > 0 and target.hp > 0:
                        total_burn = round(target.max_hp * sunfire_pct)
                        tick_damage = max(1, round(total_burn / dao_paths.FIRE_BURN_TICKS))
                        target.sunfire_burn_damage_per_tick = tick_damage
                        target.sunfire_burn_ticks_remaining = dao_paths.FIRE_BURN_TICKS
                        self._log(f"☀️ **{p['name']}**'s sunfire catches hold of {target.monster.name}!")
                    if target.hp <= 0:
                        self._log(f"💥 {target.monster.name} is defeated!")
                        self._on_enemy_defeated(target)
                        # Phoenix Feather-family physique: "defeating an enemy restores battle
                        # Qi" -- fires once per kill even within one AOE volley (each defeat is
                        # its own event), unlike the stack growth below which is once per action.
                        kill_qi_restore_pct = self._trait_bonus(p, "kill_qi_restore_pct")
                        if kill_qi_restore_pct:
                            restored = round(p["max_qi"] * kill_qi_restore_pct)
                            if restored > 0:
                                p["qi"] = min(p["max_qi"], p["qi"] + restored)
                                self._persist_qi(user_id, p)
                                self._log(f"🔥 **{p['name']}**'s kill rekindles {restored} battle Qi.")
                    elif is_freeze and random.random() < FREEZE_PROC_CHANCE:
                        target.frozen_rounds = max(target.frozen_rounds, 1)
                        self._log(f"❄️ {target.monster.name} is frozen solid and will miss its next attack!")
            # Heavenly Solar/Lunar Physique stack growth -- ONCE per action if at least one
            # target was hit, never once per target, so a Lunar Physique AOE swing that lands
            # on several enemies at once doesn't grow stacks several times faster than a
            # normal single-target attacker.
            if label == "Attack" and any_hit_landed:
                p["solar_stacks"] = min(5, p.get("solar_stacks", 0) + 1)
                p["lunar_stacks"] = min(5, p.get("lunar_stacks", 0) + 1)

        # Phase 1.5: Fire Dao Path burn ticks -- once per round, for every enemy with an
        # active burn (seeded by a landed hit somewhere in Phase 1 above), independent of
        # whose turn queued this round's actions. Can finish an enemy off on its own, same as
        # any other damage source.
        for enemy in self.enemies:
            if enemy.burn_ticks_remaining <= 0 or not enemy.alive:
                continue
            burn_damage = min(enemy.hp, enemy.burn_damage_per_tick)
            enemy.hp -= burn_damage
            enemy.burn_ticks_remaining -= 1
            self._log(f"🔥 {enemy.monster.name} burns for {burn_damage} damage!")
            if enemy.hp <= 0:
                self._log(f"💥 {enemy.monster.name} is defeated!")
                self._on_enemy_defeated(enemy)

        # Phase 1.6: Blazing Glory Sunfire Physique burn ticks -- same shape as Phase 1.5
        # above, just a separate, independently-ticking damage pool.
        for enemy in self.enemies:
            if enemy.sunfire_burn_ticks_remaining <= 0 or not enemy.alive:
                continue
            burn_damage = min(enemy.hp, enemy.sunfire_burn_damage_per_tick)
            enemy.hp -= burn_damage
            enemy.sunfire_burn_ticks_remaining -= 1
            self._log(f"☀️ {enemy.monster.name} burns in sunfire for {burn_damage} damage!")
            if enemy.hp <= 0:
                self._log(f"💥 {enemy.monster.name} is defeated!")
                self._on_enemy_defeated(enemy)

        # Phase 1.65: Bloodscale Serpent-style Bleed ticks -- once per round, for every alive
        # participant with an active bleed (seeded on a landed enemy hit -- see
        # _resolve_enemy_hit), independent of whose turn queued this round. Mirrors the
        # enemy-burn ticks above but on the player side, so a bleed can finish someone off on
        # its own -- goes through the same defeat handling _resolve_enemy_hit's landed-hit
        # branch uses (ward/escape/death-penalty), since a normal enemy attack isn't involved.
        for user_id, p in self.participants.items():
            if p.get("bleed_ticks_remaining", 0) <= 0 or p["down"]:
                continue
            bleed_damage = min(p["hp"], p["bleed_damage_per_tick"])
            p["hp"] -= bleed_damage
            p["bleed_ticks_remaining"] -= 1
            self._persist_hp(user_id, p)
            self._log(f"🩸 **{p['name']}** bleeds for {bleed_damage} damage!")
            if p["hp"] <= 0:
                p["down"] = True
                self.game.db.set_hp(user_id, 1)
                ward_name = self.game.check_and_consume_defeat_ward(user_id)
                if ward_name:
                    self._log(f"✨ **{ward_name}** activates for **{p['name']}** — knocked out, but the Qi loss is warded away!")
                elif self.game.check_and_consume_worldly_escape(user_id):
                    self._log(f"✨ **Worldly Escape Gu** activates for **{p['name']}** — knocked out, but the Qi loss is escaped entirely!")
                else:
                    bonuses = self.game.compute_equipment_bonuses(user_id)
                    reduction = bonuses.get("death_qi_loss_reduction_pct", 0)
                    qi_lost, _ = self.game.db.apply_death_penalty(user_id, reduction_pct=reduction)
                    self._log(f"💀 **{p['name']}** is knocked out, losing {qi_lost:,.2f} qi!")

        # Phase 2: flee attempts (RaidView-only — see _resolve_flee_phase's default no-op).
        self._resolve_flee_phase()

        if not self._alive_enemies():
            self._on_victory()
            self.actions.clear()
            return

        # Phase 3: enemy attacks — every living enemy hits a random alive, still-present
        # player; a Guard only reduces damage from the specific enemy it targeted. A Tank's
        # Defend Ally fully redirects whatever would've hit their chosen ally onto the Tank
        # instead (last Defend on a given ally wins if more than one Tank picks them).
        defend_map = {}  # defended_user_id -> defender_user_id
        for uid, action in self.actions.items():
            if action["type"] != "defend_ally":
                continue
            defender = self.participants.get(uid)
            if defender and not defender["down"]:
                defend_map[action["defended"]] = uid

        for idx, enemy in enumerate(self.enemies):
            if not enemy.alive:
                continue
            if enemy.frozen_rounds > 0:
                enemy.frozen_rounds -= 1
                self._log(f"🥶 {enemy.monster.name} is frozen and can't attack this round!")
                continue
            alive_ids = self._alive_participant_ids()
            if not alive_ids:
                break
            if self._maybe_handle_boss_charge(enemy, idx, alive_ids, defend_map):
                continue  # this round's "turn" was spent charging/releasing a special, not a normal attack
            target_id = random.choice(alive_ids)
            # Blood Fang Wolf-style enrage boosts this enemy's own str_multiplier -- see
            # RaidEnemy.enrage_stacks (grown in Phase 1 and _resolve_enemy_hit above).
            enrage_multiplier = 1 + enemy.monster.enrage_atk_pct_per_stack * enemy.enrage_stacks
            self._resolve_enemy_hit(enemy, idx, target_id, defend_map, enemy.monster.ability.str_multiplier * enrage_multiplier)

        # Phase 3.5: DPS-check timer (Blood Sea Demon Disciple / Blood Sea Ancestor's Blood
        # Will) -- force-kills one random alive participant once dps_check_first_turn rounds
        # have passed, and again after an ever-growing gap (5, 6, 7, 8... rounds apart) if
        # the fight is still going. A guaranteed kill, not an attack roll -- no dodge/block/
        # fatal-hit-negation applies, same as the fight simply being un-winnable in time.
        for enemy in self.enemies:
            if not enemy.alive or not enemy.monster.dps_check_first_turn:
                continue
            if self.round < enemy.dps_check_next_kill_round:
                continue
            alive_ids = self._alive_participant_ids()
            if not alive_ids:
                break
            target_id = random.choice(alive_ids)
            p = self.participants[target_id]
            p["hp"] = 0
            p["down"] = True
            self.game.db.set_hp(target_id, 1)
            self._log(f"☠️ {enemy.monster.name}'s pressure claims **{p['name']}**'s life!")
            reduction = self.game.compute_equipment_bonuses(target_id).get("death_qi_loss_reduction_pct", 0)
            qi_lost, _ = self.game.db.apply_death_penalty(target_id, reduction_pct=reduction)
            self._log(f"💀 **{p['name']}** is knocked out, losing {qi_lost:,.2f} qi!")
            enemy.dps_check_interval += enemy.monster.dps_check_interval_growth
            enemy.dps_check_next_kill_round += enemy.dps_check_interval

        self.actions.clear()
        self.round += 1
        if self.inspire_rounds_remaining > 0:
            self.inspire_rounds_remaining -= 1
        # Soul Projection is per-participant (unlike Inspire's single shared flag), so this
        # is a loop rather than one decrement.
        for p in self.participants.values():
            if p.get("soul_projection_rounds_remaining", 0) > 0:
                p["soul_projection_rounds_remaining"] -= 1
        if self.participants and all(p["down"] for p in self.participants.values()):
            self._on_wipe()

    def _on_enemy_defeated(self, enemy: "RaidEnemy"):
        """Hook for a concrete view to react to a specific enemy's defeat (RaidView's main-
        boss charge collapsing along with it). No-op by default."""
        return

    def _resolve_enemy_hit(self, enemy: "RaidEnemy", idx: int, target_id: int, defend_map: dict, str_multiplier: float, guaranteed_hit: bool = False, label: str = None):
        """Resolves one enemy attack against target_id — after any Tank Defend Ally
        redirect, Guard reduction, beast-resistance, and race/physique reduction — shared by
        both a normal enemy attack and (in /raid) the main boss's own charged special, so the
        two go through the exact same mitigation pipeline."""
        alive_ids = self._alive_participant_ids()
        redirected_from = None
        if target_id in defend_map and defend_map[target_id] in alive_ids and defend_map[target_id] != target_id:
            redirected_from = target_id
            target_id = defend_map[target_id]
        p = self.participants[target_id]
        ability_label = label or enemy.monster.ability.name
        if redirected_from is not None:
            self._log(f"🛡️ **{p['name']}** steps in to defend **{self.participants[redirected_from]['name']}** from {enemy.monster.name}'s {ability_label}!")

        action = self.actions.get(target_id)
        guard_reduction = DEFEND_ALLY_DAMAGE_REDUCTION if redirected_from is not None else 0.0
        if action and action["type"] == "guard" and action["target"] == idx:
            guard_reduction = max(guard_reduction, 1.0 if action.get("full_block") else GUARD_DAMAGE_REDUCTION)

        bonuses = self.game.compute_equipment_bonuses(target_id)
        beast_reduction = bonuses.get("beast_damage_reduction_pct", 0) if enemy.monster.monster_type == "Beast" else 0
        total_reduction = 1 - (1 - guard_reduction) * (1 - beast_reduction)
        # Rockman's "-15% dmg above 50% HP" and Rare Physique's small flat reduction.
        race_physique_reduction = chargen.race_physique_damage_reduction(
            p.get("race"), p.get("physique_tier"), p["hp"] / p["max_hp"],
        )
        if race_physique_reduction:
            total_reduction = 1 - (1 - total_reduction) * (1 - race_physique_reduction)
        # Iron Skin-family physique's Guard stacks (permanent for the rest of the encounter)
        # and Stone Muscle-family physique's high-HP damage reduction — mirrors hunt.py's
        # identical _monster_turn handling.
        guard_stack_reduction = self._trait_bonus(p, "guard_stack_def_pct") * p.get("guard_stacks", 0)
        if guard_stack_reduction:
            total_reduction = 1 - (1 - total_reduction) * (1 - guard_stack_reduction)
        if p["hp"] > p["max_hp"] * 0.6:
            high_hp_reduction = self._trait_bonus(p, "high_hp_damage_reduction_pct")
            if high_hp_reduction:
                total_reduction = 1 - (1 - total_reduction) * (1 - high_hp_reduction)
        if total_reduction >= 1.0:
            self._log(f"🛡️ **{p['name']}** fully blocks {enemy.monster.name}'s {ability_label}!")
            return

        # Frost Soul's Soul Projection amplifies dodge/ignore-attack specifically on THIS
        # (incoming-attack) call — never a player's own Phase 1 attack, which doesn't read
        # either kwarg at all.
        attacker_stats, _, sp = self._attacker_stats(target_id, p)

        # Blood Sea Ancestor monster mechanics (see monsters.MonsterAbility's own added
        # fields) -- execute/bleed/debuff apply to THIS hit only; Blood Gu Abomination
        # (monster.random_blood_gu) re-picks a random mode every attack instead of reading a
        # fixed ability, at the module's own fixed RANDOM_BLOOD_GU_* magnitudes.
        execute_pct = enemy.monster.ability.execute_damage_pct
        bleed_pct = enemy.monster.ability.bleed_damage_pct
        debuff_spd_pct = enemy.monster.ability.debuff_spd_pct
        debuff_dodge_pct = enemy.monster.ability.debuff_dodge_pct
        if enemy.monster.random_blood_gu:
            mode = random.choice(("execute", "bleed", "debuff"))
            execute_pct = RANDOM_BLOOD_GU_EXECUTE_PCT if mode == "execute" else 0.0
            bleed_pct = RANDOM_BLOOD_GU_BLEED_PCT if mode == "bleed" else 0.0
            debuff_spd_pct = RANDOM_BLOOD_GU_DEBUFF_SPD_PCT if mode == "debuff" else 0.0
            debuff_dodge_pct = RANDOM_BLOOD_GU_DEBUFF_DODGE_PCT if mode == "debuff" else 0.0
        if debuff_spd_pct:
            attacker_stats = {**attacker_stats, "spd_stat": round(attacker_stats["spd_stat"] * (1 - debuff_spd_pct))}
        damage_pct_bonus = execute_pct if (p["hp"] > 0 and p["hp"] < p["max_hp"] * 0.5) else 0.0

        result = combat.resolve_attack(
            enemy.stats(), attacker_stats, str_multiplier=str_multiplier, incoming_reduction=total_reduction,
            guaranteed_hit=guaranteed_hit, ignore_chance=bonuses.get("ignore_attack_chance", 0) + sp.get("ignore_attack_chance", 0),
            dodge_chance_bonus=bonuses.get("dodge_chance_pct", 0) + sp.get("dodge_chance_pct", 0) - debuff_dodge_pct,
            lifesteal_percent=enemy.monster.ability.lifesteal_percent, damage_pct_bonus=damage_pct_bonus,
        )
        if not result.hit:
            self._log(f"❌ {enemy.monster.name} attacks **{p['name']}** but misses!")
        elif result.dodged:
            self._log(f"💨 **{p['name']}** dodges {enemy.monster.name}'s {ability_label}!")
            # Swift Foot-family physique's Momentum — only the FIRST dodge each encounter
            # arms the bonus (consumed in Phase 1's attack handling above).
            if not p.get("dodge_momentum_triggered") and self._trait_bonus(p, "dodge_momentum_str_bonus_pct"):
                p["dodge_momentum_pending"] = True
                p["dodge_momentum_triggered"] = True
        elif result.ignored:
            self._log(f"🛡️ **{p['name']}**'s Gu shrugs off {enemy.monster.name}'s attack entirely!")
        elif p["hp"] - result.damage <= 0 and (self._try_negate_fatal_hit(target_id, p) or self._try_avatar_fatal_block(target_id, p)):
            self._log(f"✨ {enemy.monster.name}'s {ability_label} should have killed **{p['name']}** — their body refuses to fall!")
        else:
            p["hp"] = max(0, p["hp"] - result.damage)
            self._persist_hp(target_id, p)
            crit = " (Critical!)" if result.crit else ""
            heal_text = ""
            if result.heal:
                enemy.hp = min(enemy.max_hp, enemy.hp + result.heal)
                heal_text = f" It recovers {result.heal} HP."
            self._log(
                (f"🩸 {enemy.monster.name} hits **{p['name']}** for {result.damage} damage{crit} with {ability_label}.{heal_text}" if label
                 else f"🩸 {enemy.monster.name} hits **{p['name']}** for {result.damage} damage{crit}.{heal_text}")
            )
            if bleed_pct > 0 and p["hp"] > 0:
                p["bleed_damage_per_tick"] = max(1, round(result.damage * bleed_pct))
                p["bleed_ticks_remaining"] = BLEED_TICKS
                self._log(f"🩸 **{p['name']}** begins bleeding!")
            if enemy.monster.enrage_stack_cap > 0:
                enemy.enrage_stacks = min(enemy.monster.enrage_stack_cap, enemy.enrage_stacks + 1)
            if p["hp"] <= 0:
                p["down"] = True
                self.game.db.set_hp(target_id, 1)
                ward_name = self.game.check_and_consume_defeat_ward(target_id)
                if ward_name:
                    self._log(f"✨ **{ward_name}** activates for **{p['name']}** — knocked out, but the Qi loss is warded away!")
                elif self.game.check_and_consume_worldly_escape(target_id):
                    self._log(f"✨ **Worldly Escape Gu** activates for **{p['name']}** — knocked out, but the Qi loss is escaped entirely!")
                else:
                    # Consolidated single read of the generic pool (root/physique/Gu/avatar
                    # soul/avatar gear all fold in there now — see
                    # GameManager.compute_equipment_bonuses) instead of separate manual reads
                    # per source, which would double-count once this key also lives in
                    # SPECIAL_BONUS_KEYS.
                    reduction = bonuses.get("death_qi_loss_reduction_pct", 0)
                    qi_lost, _ = self.game.db.apply_death_penalty(target_id, reduction_pct=reduction)
                    self._log(f"💀 **{p['name']}** is knocked out, losing {qi_lost:,.2f} qi!")
            # Immovable Mountain Physique: surviving a landed hit reflects a portion of the
            # damage taken straight back at the attacker -- guaranteed (no separate hit/dodge/
            # crit roll of its own), mirrors hunt.py's identical _monster_turn handling. A
            # retaliation kill here is left for the next round's own Phase 2 alive-enemies
            # check to notice, same precedent Phase 1.5's own burn-tick kills already set.
            if p["hp"] > 0 and enemy.hp > 0:
                retaliation_pct = self._trait_bonus(p, "retaliation_damage_pct")
                if retaliation_pct > 0:
                    retaliation_damage = max(1, round(result.damage * retaliation_pct))
                    enemy.hp = max(0, enemy.hp - retaliation_damage)
                    self._log(f"🪨 **{p['name']}** retaliates for {retaliation_damage} damage!")
                    if enemy.hp <= 0:
                        self._log(f"💥 {enemy.monster.name} is defeated!")
                        self._on_enemy_defeated(enemy)

    # -- shared action handlers (Attack/Guard/Empower/Gu Ability/Class Ability/Killer Move/
    # Soul Projection/Potion menu) -- concrete views wire buttons directly to these. -------

    async def _on_attack(self, interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        empowered = await asyncio.to_thread(self._consume_empower_cost, interaction.user.id, p)
        p["empowered"] = False
        await interaction.response.defer()
        await self._submit_action(interaction.user.id, {"type": "attack", "target": self._resolve_target_index(p), "guaranteed": empowered})

    async def _on_guard(self, interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        empowered = await asyncio.to_thread(self._consume_empower_cost, interaction.user.id, p)
        p["empowered"] = False
        # Iron Skin-family physique's Guard stack (permanent for the rest of the encounter —
        # see _resolve_enemy_hit) and River Walker-family physique's Guard/potion Qi restore.
        p["guard_stacks"] = min(2, p.get("guard_stacks", 0) + 1)
        await asyncio.to_thread(self._apply_guard_or_potion_qi_restore, interaction.user.id, p)
        target_idx = self._resolve_target_index(p)
        await interaction.response.defer()
        await self._submit_action(interaction.user.id, {"type": "guard", "target": target_idx, "full_block": empowered})

    async def _on_toggle_empower(self, interaction):
        p = self.participants.get(interaction.user.id)
        if p is None:
            await interaction.response.send_message("Join the fight before acting!", ephemeral=True)
            return
        if p["down"]:
            await interaction.response.send_message("You've been knocked out.", ephemeral=True)
            return
        if interaction.user.id in self.actions:
            await interaction.response.send_message("You've already locked in your action for this round.", ephemeral=True)
            return
        if not p["empowered"] and p["qi"] < EMPOWER_QI_COST:
            await interaction.response.send_message(f"Not enough battle Qi to Empower (needs {EMPOWER_QI_COST}).", ephemeral=True)
            return
        p["empowered"] = not p["empowered"]
        await asyncio.to_thread(self._build_components)
        embed = await asyncio.to_thread(self.build_embed)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _on_gu_ability(self, interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        gu = await asyncio.to_thread(self._equipped_gu, interaction.user.id)
        ability = gu.active_ability if gu else None
        if not ability:
            await interaction.response.send_message("You have no active Gu ability equipped.", ephemeral=True)
            return
        # Sturdy Frame-family physique's "first Gu activation each encounter costs 1 less
        # Qi" — applied before the affordability check, mirrors hunt.py's identical handling.
        qi_cost = ability.qi_cost
        if not p.get("first_gu_use_discounted"):
            discount = self._trait_bonus(p, "first_gu_use_discount_flat")
            if discount:
                qi_cost = max(0, qi_cost - discount)
                p["first_gu_use_discounted"] = True
        if p["qi"] < qi_cost:
            await interaction.response.send_message(f"Not enough Qi to use {ability.name} (needs {qi_cost}).", ephemeral=True)
            return

        def _resolve():
            p["qi"] -= qi_cost
            self._persist_qi(interaction.user.id, p)
            self._track_battle_qi_spent(p, qi_cost)

        await asyncio.to_thread(_resolve)
        await interaction.response.defer()
        await self._submit_action(interaction.user.id, {"type": "gu", "target": self._resolve_target_index(p), "ability": ability})

    async def _on_killer_move(self, interaction):
        """Additive alongside _on_gu_ability above, not a replacement -- see hunt.py's
        identical twin for the full reasoning. A fresh DB read for the equipped move (not the
        cached participant dict `p`) mirrors _equipped_gu's own "always live" convention."""
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        player_row = await asyncio.to_thread(self.game.get_player_stats, interaction.user.id, p["name"])
        move = await asyncio.to_thread(self.game.get_equipped_killer_move, player_row, "combat")
        if not move:
            await interaction.response.send_message("You have no Killer Move equipped in your Combat slot.", ephemeral=True)
            return
        qi_cost = await asyncio.to_thread(self.game.killer_move_qi_cost, player_row, move)
        if p["qi"] < qi_cost:
            await interaction.response.send_message(f"Not enough Qi to use {move['name']} (needs {qi_cost:,}).", ephemeral=True)
            return
        p["qi"] -= qi_cost
        await asyncio.to_thread(self._persist_qi, interaction.user.id, p)
        await interaction.response.defer()
        if move["kind"] == "damage":
            await self._submit_action(interaction.user.id, {"type": "killer_move", "target": self._resolve_target_index(p), "move": move})
        else:
            # Buff-kind: applied immediately (no target/enemy resolution needed) -- the
            # queued action is just a placeholder so round-completion tracking still counts
            # this as this player's turn, same as Guard/Defend Ally's own non-attack actions.
            await asyncio.to_thread(self.game.apply_killer_move_buff, interaction.user.id, player_row, move)
            self._log(f"✨ **{p['name']}**'s {move['name']} surges through them!")
            await self._submit_action(interaction.user.id, {"type": "killer_move_buff"})

    async def _on_class_ability(self, interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        class_name = p.get("character_class")

        if class_name == "Tank":
            alive_allies = [(uid, ally) for uid, ally in self.participants.items() if not ally["down"] and uid != interaction.user.id]
            if not alive_allies:
                await interaction.response.send_message("There's no one else alive to defend.", ephemeral=True)
                return
            picker = AllyPickerView(self, interaction.user.id, alive_allies)
            await interaction.response.send_message("Choose who to Defend this round:", view=picker, ephemeral=True)
            return

        if class_name == "Support":
            await interaction.response.defer()
            await self._submit_action(interaction.user.id, {"type": "inspire"})
            return

        if class_name == "Frostbinder":
            await interaction.response.defer()
            await self._submit_action(interaction.user.id, {"type": "freeze", "target": self._resolve_target_index(p)})
            return

        await interaction.response.send_message("You haven't chosen a class yet — run `/choose_class` to unlock a class ability.", ephemeral=True)

    async def _on_soul_projection(self, interaction):
        """Independent of class -- gated on having chosen an avatar soul via /avatar instead.
        Qi is spent immediately (like Empower's own cost, see _consume_empower_cost) rather
        than at round-resolution time; the buff itself is applied in Phase 0.5 of
        _resolve_round, live before Phase 1 processes this SAME action as a real strike
        against the caster's current target (see Phase 1's `is_soul_projection` branch) --
        not just a buff-and-pass like Inspire."""
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        soul = avatar.get_avatar_soul(p.get("avatar_soul"))
        if soul is None:
            await interaction.response.send_message(
                "Your avatar hasn't chosen a soul yet — run `/avatar` to awaken it.", ephemeral=True,
            )
            return
        if p["qi"] < avatar.SOUL_PROJECTION_QI_COST:
            await interaction.response.send_message(
                f"Not enough battle Qi for Soul Projection (needs {avatar.SOUL_PROJECTION_QI_COST:,}).", ephemeral=True,
            )
            return
        p["qi"] -= avatar.SOUL_PROJECTION_QI_COST
        await asyncio.to_thread(self._persist_qi, interaction.user.id, p)
        await interaction.response.defer()
        await self._submit_action(interaction.user.id, {"type": "soul_projection", "target": self._resolve_target_index(p)})

    async def _use_defend_ally_for(self, interaction, defender_id: int, defended_id: int):
        p, error = self._validate_actor(defender_id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        defended = self.participants.get(defended_id)
        if defended is None or defended["down"]:
            await interaction.response.send_message("That ally can't be defended right now.", ephemeral=True)
            return
        await interaction.response.edit_message(content=f"🛡️ Defending **{defended['name']}** this round.", view=None)
        await self._submit_action(defender_id, {"type": "defend_ally", "defended": defended_id})

    async def _on_open_potion_menu(self, interaction):
        p, error = self._validate_actor(interaction.user.id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        if p["potions_used"] >= POTION_USE_CAP:
            await interaction.response.send_message(f"You've hit this fight's potion cap ({POTION_USE_CAP}).", ephemeral=True)
            return
        inventory = await asyncio.to_thread(self.game.get_inventory, interaction.user.id)
        usable = [
            item for item in ITEMS.values()
            if item.category in ("Healing", "Pills") and item.use is not None and inventory.get(item.name, 0) > 0
        ]
        if not usable:
            await interaction.response.send_message("You don't have any usable potions or pills.", ephemeral=True)
            return
        picker = PotionPickerView(self, interaction.user.id, inventory, usable)
        await interaction.response.send_message("Pick a potion/pill to use:", view=picker, ephemeral=True)

    async def _use_potion_for(self, interaction, user_id: int, item_name: str):
        p, error = self._validate_actor(user_id)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        if p["potions_used"] >= POTION_USE_CAP:
            await interaction.response.send_message(f"You've hit this fight's potion cap ({POTION_USE_CAP}).", ephemeral=True)
            return
        ok, message = await asyncio.to_thread(self.game.use_item, user_id, p["name"], item_name)
        if not ok:
            await interaction.response.send_message(message, ephemeral=True)
            return
        p["potions_used"] += 1
        fresh = await asyncio.to_thread(self.game.get_player_stats, user_id, p["name"])
        p["hp"] = min(p["max_hp"], fresh["hp"] + p.get("hp_bonus", 0))
        await asyncio.to_thread(self._apply_guard_or_potion_qi_restore, user_id, p)
        await interaction.response.send_message(f"🧪 Used **{item_name}** — {message}", ephemeral=True)
        await self._submit_action(user_id, {"type": "potion", "item_name": item_name})


class PotionPickerView(GameView):
    """Ephemeral, per-player potion menu opened by a team battle's "Use Potion/Pill" button.
    Built fresh from just the clicking player's inventory, so it's naturally well under
    Discord's 25-option cap on a Select — unlike a select living directly on the shared
    message, which every participant sees and which would have to list every usable item in
    the whole game rather than just what one player actually owns."""

    def __init__(self, battle_view, user_id: int, inventory: dict, usable: list):
        super().__init__(timeout=60)
        select = discord.ui.Select(
            placeholder="Use a potion/pill...",
            options=[
                discord.SelectOption(label=f"{item.name} x{inventory[item.name]}", value=item.name, description=item.description[:100])
                for item in usable[:25]
            ],
        )

        async def on_pick(interaction):
            await battle_view._use_potion_for(interaction, user_id, select.values[0])

        select.callback = on_pick
        self.add_item(select)


class AllyPickerView(GameView):
    """Ephemeral menu opened by a Tank's "Class Ability" button (Defend Ally) — lets them
    pick which currently-alive ally to protect this round without needing a shared select
    living directly on the message (same reasoning as PotionPickerView)."""

    def __init__(self, battle_view, defender_id: int, alive_allies: list):
        super().__init__(timeout=60)
        select = discord.ui.Select(
            placeholder="Defend who?",
            options=[discord.SelectOption(label=ally["name"], value=str(uid)) for uid, ally in alive_allies],
        )

        async def on_pick(interaction):
            await battle_view._use_defend_ally_for(interaction, defender_id, int(select.values[0]))

        select.callback = on_pick
        self.add_item(select)
