import asyncio
import dataclasses
import json
import math
import os
import random
import time
from typing import Optional

from config import IMAGE_CACHE_DIR

from . import (
    accessories_data, accessories_gen, alchemy, avatar, avatar_gear, black_heaven, blacksmith, canon_gu, chargen,
    combat, dao_companion, dao_essences, dao_paths, discovery_gen, equipment, exploration, gathering, grotto, gu_pet,
    gu_pet_images, gu_types, inheritance_ground_data, items, killer_move_gen, manual_data, manual_gen, monsters,
    professions, realms, search_data, sects, servants, split_body, tournament, treasure_hunt, white_heaven,
    world_boss, world_regions,
)
from .content.monsters import blood_sea_ancestor
from .content.monsters import black_heaven as black_heaven_monsters
from .content import canon_gu_white_heaven
from .content import canon_gu_black_heaven
from .character_data import PATHS, PHYSIQUE_TIER_ORDER, RACES, ROOT_TIER_ORDER
from .database import GameDatabase
from .items import ITEMS, roll_essence_restoration_pill_drop
from .ui_utils import format_number

# Granted once a character is confirmed via /join. Tunable.
STARTER_INVENTORY = {
    "Minor Recovery Pill": 3,
    "Lesser Foundation Pill": 2,
}


class GameManager:
    def __init__(self, db: GameDatabase):
        self.db = db

    def get_player_stats(self, user_id: int, name: str):
        return self.db.get_or_create_player(user_id, name)

    # Primordial Origin Inheritor Root's Qi Sea Origin — fraction of CURRENT primeval essence
    # converted into a temporary cultivation-speed buff, once daily. The essence is spent
    # either way (that's the guardrail — "conversion consumes the essence and cannot be
    # reversed"), so this only ever fires when there's real essence to spend.
    QI_SEA_ORIGIN_ESSENCE_CONSUMED_PCT = 0.10
    QI_SEA_ORIGIN_BUFF_QI_MULTIPLIER_BONUS = 0.15
    QI_SEA_ORIGIN_BUFF_DURATION_SECONDS = 1800  # 30 minutes

    def cultivate(self, user_id: int, name: str):
        player = self.db.get_or_create_player(user_id, name)
        result = self.db.settle_qi(user_id)
        root_spec = chargen.get_root_spec(player["root_name"])
        if root_spec and root_spec.name == "Primordial Origin Inheritor Root" and player["primeval_essence"] > 0:
            if self.db.try_use_unique_daily_charge(user_id):
                consumed = round(player["primeval_essence"] * self.QI_SEA_ORIGIN_ESSENCE_CONSUMED_PCT)
                if consumed > 0:
                    self.db.add_primeval_essence(user_id, -consumed)
                    self.db.add_buff(
                        user_id, "Qi Sea Origin", self.QI_SEA_ORIGIN_BUFF_QI_MULTIPLIER_BONUS,
                        self.QI_SEA_ORIGIN_BUFF_DURATION_SECONDS,
                    )
        return result

    def get_qi_status(self, user_id: int, name: str) -> dict:
        self.db.get_or_create_player(user_id, name)
        return self.db.get_qi_status(user_id)

    def get_inventory(self, user_id: int):
        return self.db.get_inventory(user_id)

    def use_item(self, user_id: int, name: str, item_name: str):
        self.db.get_or_create_player(user_id, name)
        item = ITEMS.get(item_name)
        if item is None:
            return False, "That item doesn't exist."
        if item.use is None:
            return False, f"**{item_name}** can't be used yet — it's a crafting material for a future system."
        # Qi Ascension Pill (see items._use_qi_ascension_pill): db.use_qi_ascension_pill already
        # refuses a realm-locked or cap-hit use, but manager.use_item removes the item from
        # inventory BEFORE calling item.use() (below), so without this pre-check a refused pill
        # was still silently consumed for nothing. Checked here, before removal, so a doomed
        # use never costs the player the pill at all.
        if item_name.startswith("Qi Ascension Pill (T"):
            tier = item.rank
            status = self.db.get_qi_ascension_pill_status(user_id, tier)
            if not status["can_use"]:
                if status["reason"] == "realm_locked":
                    required_realm_name = realms.GREAT_REALMS[tier - 1]["name"]
                    return False, (
                        f"Your dantian isn't ready — a Tier {tier} Qi Ascension Pill requires "
                        f"**{required_realm_name}** realm. It wasn't consumed — break through further first."
                    )
                return False, (
                    f"Your dantian resists — you've already used **{status['max_uses']}** Tier {tier} Qi "
                    f"Ascension Pills, the lifetime limit for this tier. It wasn't consumed."
                )
        # Immortal Notes (see items._use_immortal_notes): same "don't consume a doomed use"
        # reasoning as the Qi Ascension Pill check above -- nothing to accelerate if the
        # player isn't currently studying a profession.
        if item_name == "Immortal Notes":
            check_player = self.db.get_or_create_player(user_id, name)
            if not check_player["studying_profession"]:
                return False, "You aren't studying anything right now — the notes have nothing to accelerate. They weren't consumed."
        # Blood Skull Gu (see items._use_blood_skull_gu): same "don't consume a doomed use"
        # reasoning -- a one-time floor-raise has nothing left to give once already there.
        if item_name == "Blood Skull Gu":
            check_player = self.db.get_or_create_player(user_id, name)
            if check_player["aptitude"] >= items.BLOOD_SKULL_GU_APTITUDE_FLOOR:
                return False, (
                    f"Your comprehension is already at least **{items.BLOOD_SKULL_GU_APTITUDE_FLOOR}** — "
                    f"the skull has nothing left to give you. It wasn't consumed."
                )
        # Food Dao Path: a scaled chance the Pill isn't actually consumed by this use. Rolled
        # before removal so a "saved" pill never even leaves the inventory (item.use's effect
        # still fires normally either way) -- but ownership still has to be checked either way,
        # a save chance isn't a way to use an item you never had.
        pill_saved = False
        if item.category == "Pills":
            save_chance = self.get_dao_path_totals(user_id).get("pill_save_chance_pct", 0)
            pill_saved = save_chance > 0 and random.random() < save_chance
        if pill_saved:
            if self.db.get_inventory(user_id).get(item_name, 0) < 1:
                return False, "You don't have any of that item."
        elif not self.db.remove_item(user_id, item_name, 1):
            return False, "You don't have any of that item."

        # Heavenly Essence Treasure Lotus-style Gu: boosts essence actually GAINED by this
        # use, diffed before/after rather than taught to items.py's use() functions
        # directly (which don't know about equipped gear, and importing GameManager into
        # items.py would be circular).
        essence_bonus_pct = self.compute_equipment_bonuses(user_id).get("essence_regen_pct", 0)
        # A Wood-family root's healing_item_pct works the same way, but against HP healed —
        # same diff-before/after trick, since items.py's use() functions have no equipped-gear/
        # root context of their own either.
        healing_bonus_pct = self._trait_bonus(self.db.get_or_create_player(user_id, name), "healing_item_pct")
        before = self.db.get_or_create_player(user_id, name)
        before_essence = before["primeval_essence"] if essence_bonus_pct > 0 else 0
        before_hp = before["hp"] if healing_bonus_pct > 0 else 0
        message = item.use(self.db, user_id)
        if essence_bonus_pct > 0:
            gained = self.db.get_or_create_player(user_id, name)["primeval_essence"] - before_essence
            if gained > 0:
                bonus = round(gained * essence_bonus_pct)
                if bonus > 0:
                    added, new_essence, max_essence = self.db.add_primeval_essence(user_id, bonus)
                    if added > 0:
                        message += f" (+{added} bonus from equipped Gu, now {new_essence}/{max_essence})"
        if healing_bonus_pct > 0:
            after = self.db.get_or_create_player(user_id, name)
            healed = after["hp"] - before_hp
            if healed > 0 and after["max_hp"] > 0:
                bonus_pct = healed * healing_bonus_pct / after["max_hp"]
                bonus_healed, new_hp, max_hp = self.db.heal_percent(user_id, bonus_pct)
                if bonus_healed > 0:
                    message += f" (+{bonus_healed} bonus HP from your root, now {new_hp}/{max_hp})"
        if pill_saved:
            message += " 🍲 Your Food Dao Path saves the pill — it wasn't consumed!"
        return True, message

    def use_item_multiple(self, user_id: int, name: str, item_name: str, quantity: int, until_stack_empty: bool = False):
        """Uses up to `quantity` of item_name back-to-back (e.g. Inventory's Use x1/x10/All
        buttons), stopping early if the player runs out. Returns (times_used, message) --
        message is the last successful use's result, or the failure reason if none succeeded.

        until_stack_empty (Use All only — see InventoryView._make_use_callback) changes what
        "stopping early" means. A pill can succeed (ok=True, its effect fires) WITHOUT
        actually leaving inventory: the Food Dao Path's pill_save_chance_pct (see use_item's
        own "pill_saved" branch) randomly saves a pill from being consumed. Use All's whole
        point is "empty my current stack," so with this flag it keeps attempting until
        `quantity` items have actually been REMOVED from inventory, not just attempted
        `quantity` times — otherwise a save silently left that pill behind even though the
        button promised the whole stack would go (found live 2026-08-09, players reporting
        Use All leaving a seemingly-random number of pills). Use x1/x10 deliberately do NOT
        get this treatment (until_stack_empty defaults False, unchanged flat-attempt-count
        loop): their contract is "N attempts," and a Food Dao Path save on one of those is a
        real, intended bonus (a free pill kept) — forcing extra attempts to guarantee exactly
        N real removals would fight that bonus instead of letting it land. The max_attempts
        safety bound guards until_stack_empty against a pathological runaway if
        pill_save_chance_pct (currently caps at 40%, see dao_paths.py) ever approached 100% —
        at today's cap the expected attempts to consume `quantity` is only ~1.7x quantity."""
        target = max(0, quantity)
        used = 0
        last_message = None

        if not until_stack_empty:
            for _ in range(target):
                ok, message = self.use_item(user_id, name, item_name)
                if not ok:
                    if used == 0:
                        return 0, message
                    break
                used += 1
                last_message = message
            return used, last_message

        consumed = 0
        attempts = 0
        max_attempts = target * 20 + 20
        while consumed < target and attempts < max_attempts:
            attempts += 1
            before = self.db.get_item_quantity(user_id, item_name)
            ok, message = self.use_item(user_id, name, item_name)
            if not ok:
                if used == 0:
                    return 0, message
                break
            used += 1
            last_message = message
            if self.db.get_item_quantity(user_id, item_name) < before:
                consumed += 1
        return used, last_message

    # -- Character creation (/join) --------------------------------------

    def set_character_name(self, user_id: int, name: str, character_name: str):
        self.db.get_or_create_player(user_id, name)
        self.db.save_character_name(user_id, character_name)

    def set_race(self, user_id: int, name: str, race_name: str):
        self.db.get_or_create_player(user_id, name)
        self.db.save_race(user_id, race_name)

    def set_path(self, user_id: int, name: str, path_name: str):
        self.db.get_or_create_player(user_id, name)
        self.db.save_path(user_id, path_name)

    def set_class(self, user_id: int, name: str, class_name: str):
        """Freely re-settable before /join confirm (matching race/path — the join_view UI
        disables the picker once confirmed, same as it does for them), where it's picked up
        by the normal confirm_character -> compute_final_stats bake-in. For a character
        already confirmed before classes existed, it's a one-time choice via /choose_class:
        there's no base roll left to re-bake from, so the class's stat_bonuses are applied
        directly on top of current stats instead (see GameDatabase.apply_class_stat_bonuses)."""
        player = self.db.get_or_create_player(user_id, name)
        character_class = chargen.get_character_class(class_name)
        if character_class is None:
            return False, "That's not a valid class."
        if player["character_confirmed"]:
            if player["character_class"]:
                return False, f"You're already a **{player['character_class']}** — classes are a one-time choice once your character is confirmed."
            self.db.apply_class_stat_bonuses(user_id, character_class.stat_bonuses)
        self.db.save_class(user_id, class_name)
        return True, f"You are now a **{class_name}** ({character_class.role}) — {character_class.ability_name}: {character_class.ability_text}"

    def reroll_root(self, user_id: int, name: str):
        self.db.get_or_create_player(user_id, name)
        claimed = self.db.get_claimed_names("root_name", "root_tier")
        tier, root_name = chargen.roll_root(claimed)
        if not self.db.reroll_root(user_id, tier, root_name):
            return False, None, None
        return True, tier, root_name

    def reroll_physique(self, user_id: int, name: str):
        self.db.get_or_create_player(user_id, name)
        claimed = self.db.get_claimed_names("physique_name", "physique_tier")
        tier, physique_name = chargen.roll_physique(claimed)
        if not self.db.reroll_physique(user_id, tier, physique_name):
            return False, None, None
        return True, tier, physique_name

    # -- /shop: paid rerolls, unlimited, gated by spirit stones instead of the free-reroll count.
    # Buying rolls a candidate but does NOT commit it — the caller (ShopView) shows the player
    # both options and calls db.set_root/set_physique only if they choose to take the new one.
    # Cost is temporarily 1 for testing; expect this to go back up.

    SHOP_ROOT_REROLL_COST = 1
    SHOP_PHYSIQUE_REROLL_COST = 1

    def buy_root_reroll(self, user_id: int, name: str):
        self.db.get_or_create_player(user_id, name)
        if not self.db.spend_spirit_stones(user_id, self.SHOP_ROOT_REROLL_COST):
            return False, None, None
        claimed = self.db.get_claimed_names("root_name", "root_tier")
        tier, root_name = chargen.roll_root(claimed)
        return True, tier, root_name

    def buy_physique_reroll(self, user_id: int, name: str):
        self.db.get_or_create_player(user_id, name)
        if not self.db.spend_spirit_stones(user_id, self.SHOP_PHYSIQUE_REROLL_COST):
            return False, None, None
        claimed = self.db.get_claimed_names("physique_name", "physique_tier")
        tier, physique_name = chargen.roll_physique(claimed)
        return True, tier, physique_name

    # Roll up to SHOP_BATCH_ROLL_COUNT at once (same per-roll cost, still paid one at a time —
    # a batch just automates repeated clicking), stopping the instant a roll comes back AT
    # LEAST as rare as the player's chosen target tier — not an exact match, so fluking into
    # something even better than what you were hunting for still stops the batch rather than
    # burning through the rest of it. The last roll made (whether it hit target or the batch
    # simply ran out of attempts/stones) is left as the pending candidate, same keep/take
    # choice as a single reroll.
    SHOP_BATCH_ROLL_COUNT = 10

    def _buy_reroll_batch(self, buy_one, tier_order: list, user_id: int, name: str, target_tier: str, attempts: int = None):
        attempts = attempts or self.SHOP_BATCH_ROLL_COUNT
        target_rank = tier_order.index(target_tier)
        rolls = []
        hit_target = False
        for _ in range(attempts):
            ok, tier, roll_name = buy_one(user_id, name)
            if not ok:
                break
            rolls.append((tier, roll_name))
            if tier_order.index(tier) >= target_rank:
                hit_target = True
                break
        return rolls, hit_target

    def buy_root_reroll_batch(self, user_id: int, name: str, target_tier: str, attempts: int = None):
        """Returns (rolls: [(tier, name), ...], hit_target: bool) — rolls is every attempt
        actually made (1 to attempts long); the last entry is the new pending candidate."""
        return self._buy_reroll_batch(self.buy_root_reroll, ROOT_TIER_ORDER, user_id, name, target_tier, attempts)

    def buy_physique_reroll_batch(self, user_id: int, name: str, target_tier: str, attempts: int = None):
        return self._buy_reroll_batch(self.buy_physique_reroll, PHYSIQUE_TIER_ORDER, user_id, name, target_tier, attempts)

    # /premium — like the shop batch above, but keeps rolling until the player either hits
    # their target tier or literally can't afford another roll, instead of stopping at a
    # fixed count. Some players have hundreds of thousands of spirit stones (each reroll
    # only costs 1), so a real "until broke" run is capped per click at
    # PREMIUM_MAX_ROLLS_PER_CLICK as a safety valve against a single button click doing
    # hundreds of thousands of DB round-trips — clicking Roll again resumes with whatever
    # stones are left.
    PREMIUM_MAX_ROLLS_PER_CLICK = 500

    def _premium_reroll(self, buy_one, tier_order: list, user_id: int, name: str, target_tier: str, max_rolls: int = None):
        max_rolls = max_rolls or self.PREMIUM_MAX_ROLLS_PER_CLICK
        target_rank = tier_order.index(target_tier)
        rolls = []
        hit_target = False
        ran_out_of_money = False
        for _ in range(max_rolls):
            ok, tier, roll_name = buy_one(user_id, name)
            if not ok:
                ran_out_of_money = True
                break
            rolls.append((tier, roll_name))
            if tier_order.index(tier) >= target_rank:
                hit_target = True
                break
        return rolls, hit_target, ran_out_of_money

    def premium_root_reroll(self, user_id: int, name: str, target_tier: str, max_rolls: int = None):
        """Returns (rolls: [(tier, name), ...], hit_target: bool, ran_out_of_money: bool)."""
        return self._premium_reroll(self.buy_root_reroll, ROOT_TIER_ORDER, user_id, name, target_tier, max_rolls)

    def premium_physique_reroll(self, user_id: int, name: str, target_tier: str, max_rolls: int = None):
        return self._premium_reroll(self.buy_physique_reroll, PHYSIQUE_TIER_ORDER, user_id, name, target_tier, max_rolls)

    # /premium — change race. Unlike root/physique above, race is a direct, deterministic
    # pick from a short named list rather than a random roll, so there's no keep/take step —
    # paying the cost just switches you immediately. Same "temporarily cheap for testing"
    # note as SHOP_ROOT_REROLL_COST/SHOP_PHYSIQUE_REROLL_COST above.
    PREMIUM_RACE_CHANGE_COST = 1

    def change_race(self, user_id: int, name: str, race_name: str):
        player = self.db.get_or_create_player(user_id, name)
        if race_name not in RACES:
            return False, "That's not a valid race."
        if player["race"] == race_name:
            return False, f"You're already **{race_name}**."
        if not self.db.spend_spirit_stones(user_id, self.PREMIUM_RACE_CHANGE_COST):
            return False, f"Needs {self.PREMIUM_RACE_CHANGE_COST} spirit stones (you have {format_number(player['spirit_stones'])})."
        self.db.save_race(user_id, race_name)
        return True, f"You are now a **{race_name}**!"

    # Fraction of currently-banked Qi lost as a one-time "settling" cost when changing
    # cultivation path — the real feature path_changes_remaining was always meant to gate
    # (it's existed as a column since character creation, unused, until now). Sovereign
    # Immortal Root's own Unique mechanic is skipping exactly this cost.
    PATH_CHANGE_SETTLING_QI_LOSS_PCT = 0.15

    def change_cultivation_path(self, user_id: int, name: str, path_name: str):
        player = self.db.get_or_create_player(user_id, name)
        if path_name not in PATHS:
            return False, "That's not a valid cultivation path."
        if player["cultivation_path"] == path_name:
            return False, f"You're already walking the **{path_name}** path."
        if player["path_changes_remaining"] <= 0:
            return False, "You have no path changes remaining."
        root_spec = chargen.get_root_spec(player["root_name"])
        skip_penalty = bool(root_spec and root_spec.skip_path_settling_penalty)
        qi_lost = 0.0
        if not skip_penalty and player["qi"] > 0:
            qi_lost = player["qi"] * self.PATH_CHANGE_SETTLING_QI_LOSS_PCT
            self.db.add_qi(user_id, -qi_lost)
        self.db.spend_path_change(user_id)
        self.db.save_path(user_id, path_name)
        penalty_text = "no settling cost — your root smooths the transition" if skip_penalty else f"losing {format_number(qi_lost)} qi as your foundation settles"
        return True, f"You now walk the **{path_name}** path ({penalty_text})."

    def confirm_character(self, user_id: int, name: str, base_stats: dict):
        player = self.db.get_or_create_player(user_id, name)
        race = chargen.get_race(player["race"])
        root_tier = chargen.get_root_tier(player["root_tier"])
        physique_tier = chargen.get_physique_tier(player["physique_tier"])
        path = chargen.get_path(player["cultivation_path"])
        character_class = chargen.get_character_class(player["character_class"])

        physique_spec = chargen.get_physique_spec(player["physique_name"])
        final_stats = chargen.compute_final_stats(base_stats, race, root_tier, physique_tier, path, character_class, physique_spec)
        player = self.db.confirm_character(user_id, final_stats)

        for item_name, quantity in STARTER_INVENTORY.items():
            self.db.add_item(user_id, item_name, quantity)

        for slot_key, item_name in equipment.STARTER_EQUIPMENT.items():
            self.db.set_equipped(user_id, slot_key, item_name)

        # A real assembled manual in the PRIMARY slot, replacing the old legacy "manual"
        # slot_key's static "First Breathing Manual" catalog item — same starting flavor
        # (+2% cultivation gain, nothing else) but through the actual primary/auxiliary
        # manual system instead of a permanently-stuck Rank F+ item cluttering every
        # equipment/profile screen forever. Hand-built rather than manual_gen.generate_manual
        # (which rolls real pages/paths/flaws at random) since every new character should get
        # the exact same simple starting manual, not a randomized one.
        starter_manual = {
            "name": "First Breathing Manual", "rank": 1, "rarity": "Common", "primary_path": "qi",
            "secondary_paths": [], "page_ids": [],
            "coherence": 60, "coherence_band": "Stable", "stability": 100,
            "comprehension": 0, "effects": {"cultivation_speed_pct": 2.0}, "flaws": [],
            "generation_seed": 0, "bound": False,
        }
        starter_manual_id = self.db.create_manual(user_id, starter_manual)
        self.db.set_equipped_manual(user_id, "primary", starter_manual_id)

        return player

    def _selection_objects(self, player):
        return (
            chargen.get_race(player["race"]),
            chargen.get_root_tier(player["root_tier"]),
            chargen.get_physique_tier(player["physique_tier"]),
            chargen.get_path(player["cultivation_path"]),
        )

    UNCOMMON_PHYSIQUE_QI_COST_REDUCTION_PCT = 0.08  # "Efficient Aperture" -- see character_data.PHYSIQUE_TIERS["Uncommon"]

    def _breakthrough_qi_required(self, player: dict, physique_tier) -> float:
        qi_required = realms.qi_required_for_next(player["realm_index"])
        if physique_tier and physique_tier.name == "Uncommon":
            qi_required *= (1 - self.UNCOMMON_PHYSIQUE_QI_COST_REDUCTION_PCT)
        return qi_required

    def breakthrough_status(self, user_id: int, name: str):
        """Realm/chance/qi info for display — doesn't attempt anything."""
        player = self.db.get_or_create_player(user_id, name)
        race, root_tier, physique_tier, path = self._selection_objects(player)
        chance = chargen.effective_breakthrough_chance(race, root_tier, physique_tier, path, player["luck_stat"])
        manual_bonus = self.compute_equipment_bonuses(user_id).get("breakthrough_success_pct", 0)
        chance = min(1.0, chance + manual_bonus)
        return {
            "player": player,
            "realm_name": realms.realm_name(player["realm_index"]),
            "next_realm_name": None if realms.is_max_realm(player["realm_index"]) else realms.realm_name(player["realm_index"] + 1),
            "qi_required": self._breakthrough_qi_required(player, physique_tier),
            "chance": chance,
            "at_max_realm": realms.is_max_realm(player["realm_index"]),
        }

    EPIC_PHYSIQUE_BREAKTHROUGH_BUFF_PCT = 0.10
    EPIC_PHYSIQUE_BREAKTHROUGH_BUFF_DURATION_SECONDS = 600  # 10 minutes
    DIVINE_PHYSIQUE_BREAKTHROUGH_BOOST_PCT = 0.20  # "Divine Aegis" -- see character_data.PHYSIQUE_TIERS["Divine"]

    def attempt_breakthrough(self, user_id: int, name: str):
        player, _ = self.db.settle_qi(user_id)  # bank latest qi before checking
        race, root_tier, physique_tier, path = self._selection_objects(player)

        if realms.is_max_realm(player["realm_index"]):
            return {"outcome": "max_realm", "player": player}

        qi_required = self._breakthrough_qi_required(player, physique_tier)
        if player["qi"] < qi_required:
            return {"outcome": "insufficient_qi", "player": player, "qi_required": qi_required}

        chance = chargen.effective_breakthrough_chance(race, root_tier, physique_tier, path, player["luck_stat"])
        equip_bonuses = self.compute_equipment_bonuses(user_id)
        # A manual's breakthrough_success_pct (see manual_view.EFFECT_LABELS) is a passive,
        # always-on addition — unlike the once-daily accessory boost just below, it applies
        # every attempt for as long as the manual stays equipped.
        chance = min(1.0, chance + equip_bonuses.get("breakthrough_success_pct", 0))
        # Divine Physique's "Divine Aegis" — once per UTC day, the first attempt gets a real
        # chance boost (not previewed in breakthrough_status, same as Mythic's fatal-hit save
        # not being previewed either — it's a use-it-or-lose-it daily charge, not a standing
        # bonus). Checked/consumed here rather than through consume_pending_breakthrough_boost
        # below since that mechanism is for externally-triggered (accessory) boosts that get
        # manually armed in advance; this one self-arms once per day with no activation step.
        divine_boost_used = physique_tier is not None and physique_tier.name == "Divine" and self.db.try_use_daily_divine_breakthrough_boost(user_id)
        if divine_boost_used:
            chance = min(1.0, chance + self.DIVINE_PHYSIQUE_BREAKTHROUGH_BOOST_PCT)
        # An activated breakthrough-boost accessory/artifact (Blood-Debt Ring, Empty
        # Aperture Ring, Ring of the Ten-Thousand-Trial Survivor at 10 stacks, ...) — see
        # activate_accessory_artifact — applies here and is consumed on this attempt
        # regardless of outcome, same as the doc's own "applies a meaningful penalty"/
        # "second result is final" framing for these once-daily effects.
        boost = self.consume_pending_breakthrough_boost(user_id, player)
        if boost.get("chance_pct"):
            chance = min(1.0, chance + boost["chance_pct"])
        if boost.get("cost_reduction_pct"):
            qi_required = max(qi_required * 0.70, qi_required * (1 - boost["cost_reduction_pct"]))
        success = random.random() < chance
        red_lotus_retried = False

        bonus_qi = 0.0
        comprehension_proc = False
        stat_grown = None

        if not success:
            self.record_failed_breakthrough_insight(user_id)
            # A manual's deviation_resistance_pct (see manual_view.EFFECT_LABELS) softens the
            # backlash of a failed attempt by refunding part of the qi that would otherwise be
            # lost — floored at 20% of the original cost still lost, so failure never becomes
            # free no matter how much resistance is stacked. An Earth-family root's
            # breakthrough_qi_loss_reduction_pct (see character_data.CharacterTraitSpec) folds
            # into the exact same reduction, subject to the same floor.
            deviation_resistance = equip_bonuses.get("deviation_resistance_pct", 0) + self._trait_bonus(player, "breakthrough_qi_loss_reduction_pct")
            qi_required = max(qi_required * 0.20, qi_required * (1 - deviation_resistance)) if deviation_resistance else qi_required
            # Red Lotus Inheritor Root's Red Lotus Reversal — once every 7 days, a failed
            # breakthrough refunds 70% of what it would otherwise cost and grants one
            # immediate free retry at -10 percentage points success chance. The retry's own
            # result is final (it can't chain into a second reversal) and costs nothing
            # further — apply_breakthrough below only ever charges qi ONCE per call, so this
            # re-rolls success BEFORE that single charge happens rather than refunding and
            # re-charging as two separate DB writes.
            root_spec = chargen.get_root_spec(player["root_name"])
            if root_spec and root_spec.name == "Red Lotus Inheritor Root" and self.db.try_use_unique_weekly_charge(user_id):
                qi_required *= 0.30  # 70% of the (already-reduced) loss refunded
                retry_chance = max(chargen.MIN_BREAKTHROUGH_CHANCE, chance - 0.10)
                success = random.random() < retry_chance
                red_lotus_retried = True
                if not success:
                    self.record_failed_breakthrough_insight(user_id)

        if success:
            # Wisdom Dao Path folds straight into the same dao_comprehension_pct mechanic race/
            # root/physique/path already grant (see game/dao_paths.py's own docstring on why
            # this key was reused rather than invented fresh).
            dao_bonus = chargen.effective_dao_comprehension_bonus(race, root_tier, physique_tier, path)
            dao_bonus += self.get_dao_path_totals(user_id).get("dao_comprehension_pct", 0)
            if dao_bonus > 0 and random.random() < dao_bonus:
                bonus_qi = qi_required * chargen.DAO_COMPREHENSION_BONUS_QI_FRACTION
                comprehension_proc = True

            # "Every breakthrough grants +1 random permanent stat" (Human race, Legendary physique)
            grants_stat_growth = (race and race.name == "Human") or (physique_tier and physique_tier.name == "Legendary")
            if grants_stat_growth:
                stat_grown = random.choice(chargen.STAT_GROWTH_KEYS)

        old_realm_index = player["realm_index"]
        old_realm = realms.realm_name(old_realm_index)
        great_realm_crossing = realms.is_great_realm_crossing(old_realm_index)
        power_multiplier = realms.stat_multiplier_for_next(old_realm_index)
        # Computed analytically (not diffed from the DB) so it always matches the pre-attempt
        # preview exactly and never double-counts the separate "bonus random stat" roll.
        power_growth = chargen.project_power_growth(player, power_multiplier) if success else {}
        player = self.db.apply_breakthrough(user_id, qi_required, success, bonus_qi, stat_grown, power_multiplier)

        # One-time Dao Marks lump sum for breaking through INTO one of Spirit Severing's own 4
        # substages (see dao_paths.breakthrough_marks) — None for every other breakthrough.
        dao_marks_granted = 0
        if success:
            new_stage = realms.STAGES[player["realm_index"]]
            marks = dao_paths.breakthrough_marks(new_stage.great_realm_name, new_stage.substage_name)
            if marks:
                self.db.add_dao_marks(user_id, marks)
                dao_marks_granted = marks

        # A Dao Realm substage breakthrough earns a Dao Essence pick (see game/dao_essences.py /
        # /dao_essence) — flagged here rather than granted automatically, same "point the player
        # at a separate command" precedent as dao_marks_granted above, since a pick is a real
        # choice among 9 named options, not a number to just add.
        dao_essence_pick_available = success and self.get_dao_essence_status(user_id, player)["pick_available"]

        # "Gain a temporary stat boost after every breakthrough" (Epic Physique) — sized off
        # the player's fresh post-breakthrough stats, so it scales naturally with realm.
        epic_vigor_granted = False
        if success and physique_tier and physique_tier.name == "Epic":
            pct = self.EPIC_PHYSIQUE_BREAKTHROUGH_BUFF_PCT
            self.db.add_buff(
                user_id, "Breakthrough Vigor", 0, self.EPIC_PHYSIQUE_BREAKTHROUGH_BUFF_DURATION_SECONDS,
                str_bonus=round(player["str_stat"] * pct), atk_bonus=round(player["atk_stat"] * pct),
                def_bonus=round(player["def_stat"] * pct), spd_bonus=round(player["spd_stat"] * pct),
            )
            epic_vigor_granted = True

        # Godly Physique's own signature mechanic — every successful breakthrough (not just
        # Great Realm crossings, unlike Boundless Foundation Root's %-of-current mechanic
        # right below) permanently grows one random foundation stat by 2% of its CURRENT
        # value — "current" meaning the fresh post-breakthrough `player` row above, so it
        # scales off the stat AFTER this breakthrough's own power_multiplier already applied,
        # same ordering Boundless Foundation uses. Uncapped, same as Primordial Origin Body's
        # own flat-growth mechanic further below.
        godly_stat_grown = None
        godly_stat_bonus = 0
        if success and physique_tier and physique_tier.name == "Godly":
            godly_stat_grown = random.choice(chargen.STAT_GROWTH_KEYS)
            godly_stat_bonus = max(1, round(player[godly_stat_grown] * 0.02))
            self.db.add_permanent_stat_bonus(user_id, godly_stat_grown, godly_stat_bonus)
            player = self.db.get_or_create_player(user_id, name)

        # Limitless Inheritor Root's Boundless Foundation — every Great Realm crossing (up
        # to 5 times total, tracked via unique_permanent_counter) permanently grants +1% of
        # the player's CURRENT value in a rotating foundation-stat family. Rotates through
        # chargen.STAT_GROWTH_KEYS by the player's own crossing count so all six stats get a
        # turn roughly evenly rather than always hitting the same one.
        boundless_foundation_stat = None
        if success and great_realm_crossing:
            root_spec = chargen.get_root_spec(player["root_name"])
            if root_spec and root_spec.name == "Limitless Inheritor Root":
                if self.db.try_increment_unique_permanent_counter(user_id, cap=5):
                    boundless_foundation_stat = chargen.STAT_GROWTH_KEYS[player["unique_permanent_counter"] % len(chargen.STAT_GROWTH_KEYS)]
                    bonus = max(1, round(player[boundless_foundation_stat] * 0.01))
                    self.db.add_permanent_stat_bonus(user_id, boundless_foundation_stat, bonus)
                    player = self.db.get_or_create_player(user_id, name)

        # Immortal Blood-family physique — "Great Realm breakthroughs grant a stronger
        # temporary Vigor buff" than Epic Physique's own version above, sized the same way
        # (a % of the player's fresh post-breakthrough stats) but gated on a GREAT REALM
        # crossing specifically rather than every breakthrough. [The source brief's other
        # clause, "severe deviation is slightly less likely", was dropped: deviation_stress
        # is tracked (see database.py) but never actually consumed by any breakthrough-failure
        # or deviation-event logic anywhere in this codebase, so there's no real chance to
        # reduce.]
        if success and great_realm_crossing:
            vigor_pct = self._trait_bonus(player, "great_realm_vigor_buff_pct")
            if vigor_pct:
                self.db.add_buff(
                    user_id, "Great Realm Vigor", 0, self.EPIC_PHYSIQUE_BREAKTHROUGH_BUFF_DURATION_SECONDS,
                    str_bonus=round(player["str_stat"] * vigor_pct), atk_bonus=round(player["atk_stat"] * vigor_pct),
                    def_bonus=round(player["def_stat"] * vigor_pct), spd_bonus=round(player["spd_stat"] * vigor_pct),
                )

        # Primordial Origin Body (Divine physique)'s own Great Realm mechanic — "permanently
        # add +1 to two different random foundation stats" on every crossing (uncapped, per
        # the source brief — unlike Limitless Inheritor Root's own similar mechanic, this one
        # has no stated cap). ["Manual path conflicts reduced slightly" was dropped, same
        # reasoning as the root ladder's own Void Root/Primordial Origin Root: no such
        # conflict system exists to reduce.]
        physique_spec = chargen.get_physique_spec(player["physique_name"])
        if success and great_realm_crossing and physique_spec and physique_spec.name == "Primordial Origin Body":
            two_stats = random.sample(chargen.STAT_GROWTH_KEYS, 2)
            for stat_key in two_stats:
                self.db.add_permanent_stat_bonus(user_id, stat_key, 1)
            player = self.db.get_or_create_player(user_id, name)

        return {
            "outcome": "success" if success else "failure",
            "player": player,
            "chance": chance,
            "qi_cost": qi_required,
            "old_realm_name": old_realm,
            "new_realm_name": realms.realm_name(player["realm_index"]) if success else old_realm,
            "new_realm_description": realms.realm_description(player["realm_index"]) if success else None,
            "great_realm_crossing": great_realm_crossing if success else False,
            "power_multiplier": power_multiplier,
            "power_growth": power_growth,
            "bonus_qi": bonus_qi,
            "comprehension_proc": comprehension_proc,
            "stat_grown": stat_grown,
            "godly_stat_grown": godly_stat_grown,
            "godly_stat_bonus": godly_stat_bonus,
            "epic_vigor_granted": epic_vigor_granted,
            "divine_boost_used": divine_boost_used,
            "red_lotus_retried": red_lotus_retried,
            "boundless_foundation_stat": boundless_foundation_stat,
            "dao_marks_granted": dao_marks_granted,
            "dao_essence_pick_available": dao_essence_pick_available,
        }

    # -- Economy: spirit stones -> primeval essence -> qi -----------------

    def exchange_stones_for_essence(self, user_id: int, name: str, amount: int):
        self.db.get_or_create_player(user_id, name)
        return self.db.exchange_stones_for_essence(user_id, amount)

    def consume_essence_for_qi(self, user_id: int, name: str, amount: int):
        self.db.get_or_create_player(user_id, name)
        purity_bonus = self.compute_equipment_bonuses(user_id).get("essence_purity_pct", 0)
        return self.db.consume_essence_for_qi(user_id, amount, purity_bonus)

    # -- Player-to-player trading -------------------------------------------

    def can_start_trade(self, initiator_id: int, target_id: int) -> Optional[str]:
        """Returns an error message if a trade can't start, else None."""
        if initiator_id == target_id:
            return "You can't trade with yourself."
        if self.db.has_active_trade(initiator_id):
            return "You're already in an active trade."
        if self.db.has_active_trade(target_id):
            return "That player is already in an active trade."
        return None

    def start_trade(self, initiator_id: int, target_id: int) -> int:
        return self.db.create_trade(initiator_id, target_id)

    def start_gamble(self, initiator_id: int, target_id: int) -> int:
        return self.db.create_trade(initiator_id, target_id, mode="gamble")

    def get_trade(self, trade_id: int):
        return self.db.get_trade(trade_id)

    def get_trade_offer(self, trade_id: int, user_id: int) -> dict:
        return self.db.get_trade_offer(trade_id, user_id)

    def accept_trade(self, trade_id: int):
        self.db.set_trade_status(trade_id, "active")

    def decline_trade(self, trade_id: int):
        self.db.delete_trade(trade_id)

    def cancel_trade(self, trade_id: int):
        self.db.delete_trade(trade_id)

    def set_trade_currency(self, trade_id: int, user_id: int, name: str, currency: str, amount: int) -> int:
        """Sets this side's offered `currency` (spirit_stones/manual_ink/insight_dust — see
        GameDatabase.TRADE_CURRENCIES) to amount, clamped to what they own. Returns the
        clamped amount."""
        player = self.db.get_or_create_player(user_id, name)
        amount = max(0, min(amount, player[currency]))
        self.db.set_trade_currency(trade_id, user_id, currency, amount)
        self.db.reset_trade_confirmations(trade_id)
        return amount

    def add_trade_item(self, trade_id: int, user_id: int, name: str, item_name: str, quantity: int = 1) -> int:
        """Adds up to `quantity` more of item_name to this side's offer, clamped to how many
        are actually free to offer (owned minus already offered). Returns how many were
        actually added (0 if none were available)."""
        self.db.get_or_create_player(user_id, name)
        owned = self.db.get_inventory(user_id).get(item_name, 0)
        already_offered = self.db.get_trade_offer(trade_id, user_id)["items"].get(item_name, 0)
        added = max(0, min(quantity, owned - already_offered))
        if added <= 0:
            return 0
        self.db.add_trade_item(trade_id, user_id, item_name, added)
        self.db.reset_trade_confirmations(trade_id)
        return added

    def add_trade_page(self, trade_id: int, user_id: int, name: str, page_id: str, quantity: int = 1) -> int:
        """Offers up to `quantity` more of a manual page stack — quantity-based like
        add_trade_item (not a unique instance), same "no gate beyond ownership + quantity"
        rule dismantle_page already uses (refinement_level/studied state never blocks this).
        Returns how many were actually added (0 if none were available)."""
        self.db.get_or_create_player(user_id, name)
        owned = self.db.get_player_pages(user_id).get(page_id, {}).get("quantity", 0)
        already_offered = self.db.get_trade_offer(trade_id, user_id)["pages"].get(page_id, 0)
        added = max(0, min(quantity, owned - already_offered))
        if added <= 0:
            return 0
        self.db.add_trade_page(trade_id, user_id, page_id, added)
        self.db.reset_trade_confirmations(trade_id)
        return added

    def add_trade_crafted_gear(self, trade_id: int, user_id: int, name: str, gear_id: int) -> bool:
        """Offers a unique crafted_gear instance — same ownership rule as dismantling one
        (see dismantle_crafted_gear): must be owned and NOT currently equipped, or trading it
        away would leave the old owner's equipped slot pointing at gear that's no longer
        theirs, still counting its stats via compute_equipment_bonuses. Returns whether it
        was actually added."""
        self.db.get_or_create_player(user_id, name)
        gear = self.db.get_crafted_gear(gear_id)
        if gear is None or gear["owner_id"] != user_id:
            return False
        if gear_id in self.db.get_equipped_gear_ids(user_id).values():
            return False
        if gear_id in self.db.get_trade_offer(trade_id, user_id)["crafted_gear"]:
            return False
        display_name = blacksmith.crafted_gear_display_name(gear["base_type"], gear["tier"], gear["gear_id"])
        self.db.add_trade_crafted_gear(trade_id, user_id, gear_id, display_name)
        self.db.reset_trade_confirmations(trade_id)
        return True

    def add_trade_manual(self, trade_id: int, user_id: int, name: str, manual_id: int) -> bool:
        """Offers a unique assembled manual — same ownership rule as add_trade_crafted_gear:
        must be owned and NOT currently equipped (manuals equip through
        players.equipped_primary_manual_id/equipped_auxiliary_manual_id, not the generic
        `equipped` table crafted_gear uses). Returns whether it was actually added."""
        player = self.db.get_or_create_player(user_id, name)
        manual = self.db.get_manual(manual_id)
        if manual is None or manual["owner_id"] != user_id:
            return False
        if manual_id in (player["equipped_primary_manual_id"], player["equipped_auxiliary_manual_id"]):
            return False
        if manual_id in self.db.get_trade_offer(trade_id, user_id)["manuals"]:
            return False
        display_name = f"{manual['name']} (R{manual['rank']} {manual['rarity']})"
        self.db.add_trade_manual(trade_id, user_id, manual_id, display_name)
        self.db.reset_trade_confirmations(trade_id)
        return True

    def add_trade_accessory(self, trade_id: int, user_id: int, name: str, instance_id: int) -> bool:
        """Offers a unique accessory/artifact instance — same ownership rule as
        add_trade_crafted_gear: must be owned and NOT currently equipped. Returns whether it
        was actually added."""
        self.db.get_or_create_player(user_id, name)
        instance = self.db.get_accessory_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False
        if instance_id in self.db.get_equipped_accessory_ids(user_id).values():
            return False
        if instance_id in self.db.get_trade_offer(trade_id, user_id)["accessories"]:
            return False
        affix = self._affix_for_instance(instance)
        if affix is None:
            return False
        display_name = self._accessory_display_name(instance, affix)
        self.db.add_trade_accessory(trade_id, user_id, instance_id, display_name)
        self.db.reset_trade_confirmations(trade_id)
        return True

    def add_trade_gu_pet(self, trade_id: int, user_id: int, name: str, pet_id: int) -> bool:
        """Offers a unique Gu Pet — same one-of-a-kind shape as add_trade_manual/add_trade_
        accessory (a pet_id can only ever be offered once). Unlike those, a Gu Pet currently
        set as this player's active companion is NOT blocked from being offered — there's no
        UI path to deactivate a pet without activating a different one first (see
        gu_pet_view.py's Status tab), so blocking would strand a single-pet owner.
        GameDatabase.execute_trade/execute_gamble instead clear the sender's active_gu_pet_id
        automatically if the traded pet turns out to be it."""
        self.db.get_or_create_player(user_id, name)
        pet = self.db.get_gu_pet(pet_id)
        if pet is None or pet["owner_id"] != user_id:
            return False
        if pet_id in self.db.get_trade_offer(trade_id, user_id)["gu_pets"]:
            return False
        self.db.add_trade_gu_pet(trade_id, user_id, pet_id, gu_pet.pet_display_name(pet))
        self.db.reset_trade_confirmations(trade_id)
        return True

    def clear_trade_offer(self, trade_id: int, user_id: int):
        self.db.clear_trade_offer(trade_id, user_id)
        self.db.reset_trade_confirmations(trade_id)

    def confirm_trade(self, trade_id: int, user_id: int) -> str:
        """Marks this side confirmed; executes the trade once both sides are.
        Returns 'waiting', 'completed', or 'failed' (offer no longer affordable)."""
        self.db.set_trade_confirmed(trade_id, user_id, True)
        trade = self.db.get_trade(trade_id)
        if not (trade["initiator_confirmed"] and trade["target_confirmed"]):
            return "waiting"
        if self.db.execute_trade(trade_id):
            return "completed"
        self.db.set_trade_status(trade_id, "cancelled")
        return "failed"

    def confirm_gamble(self, trade_id: int, user_id: int) -> dict:
        """/gamble's sibling of confirm_trade -- same confirm-then-resolve-once-both-are
        shape, but a completed gamble needs to report who won and both rolls (execute_gamble
        also refuses to resolve, same as a failed afford-check, if either side's pot was
        empty). Returns {"status": "waiting"} / {"status": "completed", "winner_id",
        "initiator_roll", "target_roll"} / {"status": "failed"}."""
        self.db.set_trade_confirmed(trade_id, user_id, True)
        trade = self.db.get_trade(trade_id)
        if not (trade["initiator_confirmed"] and trade["target_confirmed"]):
            return {"status": "waiting"}
        result = self.db.execute_gamble(trade_id)
        if result:
            return {"status": "completed", **result}
        self.db.set_trade_status(trade_id, "cancelled")
        return {"status": "failed"}

    # A trade/gamble sitting unresolved this long almost always means its Discord View died
    # (most commonly a bot restart/redeploy mid-negotiation -- see the live incident this was
    # built for) rather than the players still genuinely using it. Offering an item only ever
    # writes a trade_offers bookkeeping row (see add_trade_item) -- inventory itself is never
    # touched until execute_trade/execute_gamble actually run -- so expiring a stale trade is
    # always safe, nothing to refund.
    TRADE_TIMEOUT_SECONDS = 20 * 60

    def expire_stale_trades(self) -> list:
        """Cancels every trade/gamble past TRADE_TIMEOUT_SECONDS with no resolution. Returns
        the list of expired trade rows (dicts) so the caller can DM both sides -- see
        GameCog.trade_timeout_tick."""
        cutoff = int(time.time()) - self.TRADE_TIMEOUT_SECONDS
        stale = self.db.get_stale_trades(cutoff)
        for trade in stale:
            self.db.set_trade_status(trade["id"], "cancelled")
        return stale

    # -- Equipment -----------------------------------------------------------

    def get_equipped(self, user_id: int) -> dict:
        return self.db.get_equipped(user_id)

    def equip_item(self, user_id: int, name: str, slot_key: str, item_name: str):
        player = self.db.get_or_create_player(user_id, name)
        gear = equipment.EQUIPMENT.get(item_name)
        if gear is None:
            return False, "That equipment doesn't exist."
        expected_type = equipment.SLOT_TYPE_BY_KEY.get(slot_key)
        if expected_type is None:
            return False, "That slot doesn't exist."
        if gear.slot_type != expected_type:
            return False, f"**{item_name}** doesn't fit in the {equipment.SLOT_LABEL_BY_KEY[slot_key]} slot."
        # Backstop only -- equipment_view.py's _effective_slot_keys already hides this slot
        # entirely from anyone without the physique, so this should be unreachable through the
        # normal UI. Kept anyway in case something else ever calls equip_item directly.
        if slot_key == equipment.GU_SLOT_KEY_2 and player["physique_name"] != equipment.TWIN_GU_SOVEREIGN_PHYSIQUE_NAME:
            return False, f"{equipment.TWIN_GU_SOVEREIGN_PHYSIQUE_NAME} is required to bind a second Gu."
        if self.db.get_inventory(user_id).get(item_name, 0) < 1:
            return False, f"You don't own a **{item_name}**."

        currently_equipped = self.db.get_equipped(user_id).get(slot_key)
        if currently_equipped == item_name:
            return False, f"**{item_name}** is already equipped there."
        if currently_equipped:
            self.db.add_item(user_id, currently_equipped, 1)

        self.db.remove_item(user_id, item_name, 1)
        self.db.set_equipped(user_id, slot_key, item_name)
        return True, f"Equipped **{item_name}** to {equipment.SLOT_LABEL_BY_KEY[slot_key]}."

    def unequip_item(self, user_id: int, name: str, slot_key: str):
        self.db.get_or_create_player(user_id, name)
        item_name = self.db.get_equipped(user_id).get(slot_key)
        if not item_name:
            return False, "That slot is already empty."
        # A crafted_gear or Hairy-Man-blessed Gu instance isn't inventory-tracked (owning the
        # row IS owning the piece — see database.py's crafted_gear/gu_instances table
        # docstrings), so unequipping one just clears the slot; only a catalog item needs an
        # inventory row back.
        if slot_key not in self.db.get_equipped_gear_ids(user_id) and slot_key not in self.db.get_equipped_gu_instance_ids(user_id):
            self.db.add_item(user_id, item_name, 1)
        self.db.clear_equipped(user_id, slot_key)
        return True, f"Unequipped **{item_name}** from {equipment.SLOT_LABEL_BY_KEY[slot_key]}."

    def unequip_all(self, user_id: int, name: str):
        self.db.get_or_create_player(user_id, name)
        instance_slots = set(self.db.get_equipped_gear_ids(user_id)) | set(self.db.get_equipped_gu_instance_ids(user_id))
        for slot_key, item_name in self.db.get_equipped(user_id).items():
            if slot_key not in instance_slots:
                self.db.add_item(user_id, item_name, 1)
            self.db.clear_equipped(user_id, slot_key)

    # -- Nascent Soul Avatar (Phase 1 -- see the approved plan) ---------------------------
    # Data model, /avatar menu, leveling, and the avatar's own gear only. Nothing here is
    # read by any combat code yet -- that's Phase 2 (Soul Projection in /hunt, /battlefield,
    # /raidboss_attack; soul special_bonuses actually consumed; Formation Soul's sect-raid
    # buff; the daily fatal-blow shield).

    AVATAR_SOUL_REROLL_COST = 200  # spirit stones; the very first pick is free

    # -- /hunt's own "finish the one you've got before starting another" gate ------------------
    # A hunt has no DB row of its own (pure in-memory HuntView session -- see HuntView.__init__'s
    # own docstring), unlike /discovery's active_discovery_id which points at a real row. This
    # timestamp exists purely so a second /hunt can be refused while one is still running.
    # Generous on purpose -- a genuinely long, actively-played hunt (many rounds, real clicking)
    # should never trip this; it only exists to self-heal a flag left stuck by e.g. a bot
    # restart mid-hunt, before HuntView.on_timeout ever got a chance to clear it normally.
    ACTIVE_HUNT_STALE_SECONDS = 2 * 3600

    def has_active_hunt(self, player: dict) -> bool:
        started = player["active_hunt_started_ts"]
        return bool(started) and (time.time() - started) < self.ACTIVE_HUNT_STALE_SECONDS

    def start_active_hunt(self, user_id: int):
        self.db.start_active_hunt(user_id, int(time.time()))

    def abandon_active_hunt(self, user_id: int):
        """Self-service escape hatch for a player whose active_hunt_started_ts flag is stuck
        (e.g. their original HuntView message scrolled away, or a round-resolution error left
        the view unresponsive without ever clearing their flag) -- mirrors abandon_active_raid.
        Safe to call even if they were never really stuck (a no-op UPDATE against a user_id not
        currently flagged)."""
        self.db.clear_active_hunt(user_id)

    # -- /raid's own "finish the one you've got before starting/joining another" gate ----------
    # Same reasoning as ACTIVE_HUNT_STALE_SECONDS above, but per-PARTICIPANT rather than
    # per-creator -- a raid is a shared multi-player encounter, so both starting a NEW raid and
    # JOINING an existing one need this check, and every terminal state needs to release EVERY
    # joiner's flag at once (see RaidView's own _clear_active_raid_for_all).
    ACTIVE_RAID_STALE_SECONDS = 2 * 3600

    def has_active_raid(self, player: dict) -> bool:
        started = player["active_raid_started_ts"]
        return bool(started) and (time.time() - started) < self.ACTIVE_RAID_STALE_SECONDS

    def start_active_raid(self, user_id: int):
        self.db.start_active_raid(user_id, int(time.time()))

    def abandon_active_raid(self, user_id: int):
        """Self-service escape hatch for a player whose active_raid_started_ts flag is stuck
        (e.g. their original RaidView message scrolled away, or the raid ended in a way that
        didn't clear their flag specifically -- see the flee-mid-raid fix in raid.py's own
        _resolve_round) -- clears just their own flag, with no dependency on any specific
        RaidView instance still existing or being reachable. Safe to call even if they were
        never really stuck (a no-op UPDATE against a user_id not currently flagged)."""
        self.db.clear_active_raid_bulk([user_id])

    # -- /inheritance_ground: 3-4 player INVITED team (see InheritanceGroundLobbyView), a few
    # branching-choice stages, an auto-resolved Final Trial, then the betrayal twist -- see
    # game/inheritance_ground_data.py for the content shape and game/inheritance_ground_view.py
    # for the UI. Same "one at a time" gate shape as /hunt and /raid, but bulk-cleared for the
    # WHOLE invited team together (not just the leader) at every terminal state, and shipped
    # with an Abandon escape hatch from day one -- see the raid flee bug fixed in commit
    # 0b6b712 for why that matters, rather than adding it reactively after someone gets stuck.
    ACTIVE_INHERITANCE_GROUND_STALE_SECONDS = 2 * 3600
    # Lowered from 8h now that it's open to every player (was admin-only) -- tunable.
    INHERITANCE_GROUND_COOLDOWN_SECONDS = 4 * 3600

    def has_active_inheritance_ground(self, player: dict) -> bool:
        started = player["active_inheritance_ground_started_ts"]
        return bool(started) and (time.time() - started) < self.ACTIVE_INHERITANCE_GROUND_STALE_SECONDS

    def inheritance_ground_cooldown_remaining(self, player: dict) -> int:
        return self._check_cooldown(player, "last_inheritance_ground_ts", self.INHERITANCE_GROUND_COOLDOWN_SECONDS)

    def check_inheritance_ground_eligibility(self, user_id: int, name: str) -> tuple:
        """Used both when the leader first invites AND when each invitee is about to accept --
        conditions (another run started elsewhere) can change during the lobby's own up-to-
        5-minute window, so this is re-checked fresh at both points rather than trusted from
        invite time. Deliberately does NOT gate on the invitee's own cooldown -- only the leader
        who actually runs /inheritance_ground needs to be off cooldown themselves (checked
        separately, inline, in cog.py); an invitee can join a team even while recovering from
        their own last run. Returns (ok, reason_code, remaining_cooldown_seconds) -- a code
        rather than a pre-formatted string since the two call sites need different grammar
        (cog.py's invite-time check is third-person about an invitee, InheritanceGroundLobbyView's
        accept-time check is second-person about the clicking player themselves). remaining is
        always 0 now (kept in the return shape for both call sites' sake).
        reason_code is one of "not_confirmed"/"already_active"/None (ok)."""
        player = self.db.get_or_create_player(user_id, name)
        if not player["character_confirmed"]:
            return False, "not_confirmed", 0
        if self.has_active_inheritance_ground(player):
            return False, "already_active", 0
        return True, None, 0

    def start_active_inheritance_ground(self, user_ids: list):
        self.db.start_active_inheritance_ground_bulk(user_ids, int(time.time()))

    def abandon_active_inheritance_ground(self, user_id: int):
        """Self-service escape hatch, same reasoning as abandon_active_raid above."""
        self.db.clear_active_inheritance_ground_bulk([user_id])

    def finish_inheritance_ground_run(self, user_ids: list, leader_id: int):
        """Called at every terminal state (lobby cancelled/timed out before starting, Final
        Trial failed, or the betrayal stage resolves) -- releases the active flag for the
        WHOLE team (user_ids), but only starts the cooldown for leader_id. Per explicit
        request, invited teammates who just joined someone else's run shouldn't have their
        own next run gated behind it -- only the leader who actually spent their own
        /inheritance_ground use should be on cooldown afterward."""
        now = int(time.time())
        self.db.clear_active_inheritance_ground_bulk(user_ids)
        self.db.set_inheritance_ground_cooldown_bulk([leader_id], now)

    # Bubble board (replaces the old branching-choice stages) -- team takes turns revealing
    # bubbles that are either an immediate shared treasure or a real, multi-round interactive
    # team fight against a monster that gets harder with every battle bubble revealed. See
    # InheritanceGroundView's "bubble_board"/"battle" phases for the UI/round-by-round flow.
    # BOARD_SIZE is now FIXED (not scaled by team size) and BUBBLES_PER_TEAM_MEMBER is the POP
    # CAP per member instead -- mirrors treasure_hunt.py's own "board is bigger than what you
    # actually get to explore" shape (BOARD_SIZE=25, MAX_CLICKS_PER_BOARD=7) per explicit
    # request: 20 bubbles, one guaranteed hidden Treasure among them, team only gets
    # team_size * BUBBLES_PER_TEAM_MEMBER total pops (see max_inheritance_ground_pops) --
    # most of the board, quite possibly including the Treasure, goes unpopped every run.
    INHERITANCE_GROUND_BOARD_SIZE = 20
    BUBBLES_PER_TEAM_MEMBER = 2  # pops per team member, not board size -- see the note above
    MIN_BATTLE_BUBBLES = 2  # flat, not scaled by board size -- a guaranteed minimum, same
    # "fixed multiset, then shuffle" reasoning treasure_hunt.roll_board's own guaranteed
    # treasure tile uses, rather than a per-bubble coin flip that could rarely land zero battles.
    # Battles escalate faster than Battlefield's own solo 0.15/wave (WAVE_STAT_MULTIPLIER_PER_WAVE
    # in battlefield_view.py) since a whole team is fighting together, not one player.
    BATTLE_STAT_MULTIPLIER_PER_BATTLE = 0.20

    # Every non-"battle", non-"treasure" bubble independently rolls one of these -- a dud
    # ("nothing") most of the time, sometimes a guaranteed Qi Ascension Pill (see
    # grant_inheritance_ground_pill_reward), Primeval Essence Crystals (see
    # grant_inheritance_ground_essence_crystal_reward), an Essence Restoration Pill (see
    # grant_inheritance_ground_essence_pill_reward), Tier 8 Herb (see
    # grant_inheritance_ground_material_reward), or Immortal Notes (see
    # grant_inheritance_ground_immortal_notes_reward, 2026-08-14). "treasure" is deliberately
    # NOT in this weighted pool -- it's a single guaranteed bubble instead (see
    # generate_inheritance_ground_board), same "exactly one guaranteed tile, everything else
    # weighted" split treasure_hunt.TILE_CATEGORY_WEIGHTS/roll_board uses. First-pass weights,
    # easy to retune.
    BUBBLE_OUTCOME_WEIGHT = {"nothing": 20, "ascension_pill": 15, "essence_crystal": 15, "essence_pill": 15, "materials": 15, "immortal_notes": 5}
    ESSENCE_CRYSTAL_QUANTITY_RANGE = (20, 100)
    ESSENCE_PILL_MIN_TIER = 4
    ESSENCE_PILL_MAX_TIER = 7

    def generate_inheritance_ground_board(self, team_size: int) -> list:
        """Returns INHERITANCE_GROUND_BOARD_SIZE (20) bubble labels: MIN_BATTLE_BUBBLES
        guaranteed "battle", exactly ONE guaranteed "treasure" (unpredictable position --
        mirrors treasure_hunt.roll_board's own single guaranteed tile), and the rest
        independently rolled via BUBBLE_OUTCOME_WEIGHT. team_size no longer affects the board
        itself, only how many of these 20 the team actually gets to pop -- see
        max_inheritance_ground_pops."""
        size = self.INHERITANCE_GROUND_BOARD_SIZE
        outcomes = list(self.BUBBLE_OUTCOME_WEIGHT.keys())
        weights = list(self.BUBBLE_OUTCOME_WEIGHT.values())
        filler_count = size - self.MIN_BATTLE_BUBBLES - 1  # -1 for the single guaranteed treasure
        board = ["battle"] * self.MIN_BATTLE_BUBBLES + ["treasure"] + random.choices(outcomes, weights=weights, k=filler_count)
        random.shuffle(board)
        return board

    def max_inheritance_ground_pops(self, team_size: int) -> int:
        """How many of the 20 bubbles this team's run actually gets to pop before the board
        locks and reveals what the rest held -- see InheritanceGroundView._reveal_remaining_
        bubbles. Deliberately well under INHERITANCE_GROUND_BOARD_SIZE, same scarcity
        treasure_hunt.MAX_CLICKS_PER_BOARD (7 of 25) creates."""
        return team_size * self.BUBBLES_PER_TEAM_MEMBER

    # Blood Sea Ancestor's own dedicated battle-bubble roster (see content/monsters/
    # blood_sea_ancestor.py) -- weighted by TIER (individual monsters within a tier are
    # equal-weight), each rarer tier both tougher (that file's own RARITY_MULTIPLIER) and
    # better-rewarding (BLOOD_SEA_RARITY_LOOT_SOURCE/BLOOD_SEA_RARITY_CANON_GU_ENCOUNTER
    # below, used by grant_inheritance_ground_battle_loot). "Only one ground exists so far"
    # (see cog.py's own hardcoded ground_key) -- a second ground would need this keyed by
    # ground_key instead of a flat pool.
    BLOOD_SEA_RARITY_TIER_WEIGHT = {"Common": 45, "Uncommon": 27, "Rare": 12, "Elite": 4}
    # accessories_data.LOOT_SOURCE_TABLE keys reused purely for their existing ODDS numbers
    # (no narrative connection intended) -- gives a real 4-step escalating ladder without
    # inventing a 5th/6th source_key just for this one ground.
    BLOOD_SEA_RARITY_LOOT_SOURCE = {"Common": "hunt_kill", "Uncommon": "split_body", "Rare": "raid_boss", "Elite": "world_boss"}
    BLOOD_SEA_RARITY_CANON_GU_ENCOUNTER = {"Common": "normal", "Uncommon": "elite", "Rare": "mini_boss", "Elite": "world_boss"}

    def roll_inheritance_ground_battle_monster(self, ground_key: str, battle_number: int):
        """battle_number is 1-indexed (the Nth battle bubble revealed this run), scaled up
        progressively via dataclasses.replace -- mirrors battlefield_view.py's own
        _roll_wave_monster exactly, just keyed by battle_number instead of a wave counter."""
        ground = inheritance_ground_data.GROUNDS[ground_key]
        if ground_key == "blood_sea_ancestor":
            rarities = list(blood_sea_ancestor.ALL_MONSTERS_BY_RARITY)
            rarity = random.choices(rarities, weights=[self.BLOOD_SEA_RARITY_TIER_WEIGHT[r] for r in rarities])[0]
            base = random.choice(blood_sea_ancestor.ALL_MONSTERS_BY_RARITY[rarity])
        else:
            great_realm_index = max(0, min(6, ground["gu_rank"] - 1))
            name = monsters.hunt_monster_name_for_realm(great_realm_index)
            base = monsters.MONSTERS[name]
        multiplier = 1.0 + self.BATTLE_STAT_MULTIPLIER_PER_BATTLE * (battle_number - 1)
        if multiplier == 1.0:
            return base
        return dataclasses.replace(
            base,
            hp=max(1, round(base.hp * multiplier)), atk_stat=max(1, round(base.atk_stat * multiplier)),
            str_stat=max(1, round(base.str_stat * multiplier)), def_stat=max(1, round(base.def_stat * multiplier)),
            spd_stat=max(1, round(base.spd_stat * multiplier)),
        )

    def roll_inheritance_ground_final_boss(self, ground_key: str):
        """The Final Trial's own boss (see InheritanceGroundView._on_face_trial) --
        BLOOD_SEA_ANCESTORS_BLOOD_WILL_CHANCE (1/100) of the true Ancestor's Blood Will,
        otherwise the Blood Sea Demon Disciple. Only "blood_sea_ancestor" has dedicated
        bosses defined so far -- see roll_inheritance_ground_battle_monster's identical
        "only one ground exists so far" caveat for what a second ground would need."""
        if ground_key != "blood_sea_ancestor":
            ground = inheritance_ground_data.GROUNDS[ground_key]
            great_realm_index = max(0, min(6, ground["gu_rank"] - 1))
            return monsters.MONSTERS[monsters.hunt_monster_name_for_realm(great_realm_index)]
        if random.random() < blood_sea_ancestor.BLOOD_SEA_ANCESTORS_BLOOD_WILL_CHANCE:
            return blood_sea_ancestor.BLOOD_SEA_ANCESTORS_BLOOD_WILL
        return blood_sea_ancestor.BLOOD_SEA_DEMON_DISCIPLE

    def grant_inheritance_ground_battle_loot(self, ground_key: str, team: list, monster) -> list:
        """Called once a battle bubble's guardian is actually defeated (see
        InheritanceGroundView._on_victory) -- one independent roll per team member: the
        monster's own beast-material drops (monsters.roll_loot, same as /hunt) plus a
        rarity-scaled shot at an accessory/artifact and a canon Gu, the "loot gets better as
        it gets more elite" half of the brief. A ground/monster with no rarity mapping (i.e.
        not this ground, or Formation Node) just grants the material roll with no bonus shot.
        Returns [(name, summary_text), ...]."""
        ground = inheritance_ground_data.GROUNDS[ground_key]
        rarity = blood_sea_ancestor.RARITY_BY_NAME.get(monster.name)
        results = []
        for user_id, name in team:
            material_loot = monsters.roll_loot(monster)
            for item_name, qty in material_loot.items():
                self.db.add_item(user_id, item_name, qty)
            parts = [f"{qty}x {item_name}" for item_name, qty in material_loot.items()]
            if rarity:
                source_key = self.BLOOD_SEA_RARITY_LOOT_SOURCE[rarity]
                granted = self.roll_and_grant_accessory_artifact(user_id, name, source_key, ground["gu_rank"], ground.get("tags", []))
                if granted:
                    parts.append(f"✨ {granted['affix'].name}")
                canon_drop = canon_gu.roll_canon_gu_drop(ground["gu_rank"], self.BLOOD_SEA_RARITY_CANON_GU_ENCOUNTER[rarity])
                if canon_drop:
                    self.db.add_item(user_id, canon_drop, 1)
                    parts.append(f"🐛 {canon_drop}")
            results.append((name, ", ".join(parts) if parts else "nothing this time"))
        return results

    def grant_inheritance_ground_treasure_reward(self, ground_key: str, team: list) -> list:
        """The board's single guaranteed Treasure bubble (see generate_inheritance_ground_
        board) -- one independent roll per team member, same discovery_gen.generate_loot
        machinery grant_inheritance_ground_share_reward uses for the run's own capstone
        reward. "Standard" difficulty (see search_data.DIFFICULTY_REWARD_QUALITY_PCT) -- it's
        no longer a "sometimes" bubble sitting below the Share/Backstab payout, it's the one
        real prize hidden among 20 bubbles the team might never even find; the -15%/-1 rank
        "Safe" penalty this used to roll at no longer fits that. Returns
        [(name, reward_str), ...]."""
        ground = inheritance_ground_data.GROUNDS[ground_key]
        rng = random.Random()
        results = []
        for user_id, name in team:
            category = discovery_gen.weighted_choice(search_data.INHERITANCE_FINAL_CHEST_TABLE, rng)
            reward = discovery_gen.generate_loot(category, "inheritance_ground", ground["gu_rank"], "Standard", ground.get("tags", []), rng)
            results.append((name, self.grant_reward(user_id, name, reward)))
        return results

    def grant_inheritance_ground_pill_reward(self, team: list) -> list:
        """An "ascension_pill" bubble (see generate_inheritance_ground_board) -- unlike
        items.roll_qi_ascension_pill_drop's own 1%-gated roll (used by /search_forgotten_
        blessed_land, /explore, World Boss), the bubble already committed to this outcome, so
        the grant itself is guaranteed; only the TIER is randomized, via that same module's
        own QI_ASCENSION_PILL_TIER_WEIGHTS. One independent roll per team member, same "whole
        team shares the bubble's find" shape grant_inheritance_ground_treasure_reward uses.
        Returns [(name, reward_str), ...]."""
        tiers = list(items.QI_ASCENSION_PILL_TIER_WEIGHTS.keys())
        weights = list(items.QI_ASCENSION_PILL_TIER_WEIGHTS.values())
        results = []
        for user_id, name in team:
            tier = random.choices(tiers, weights=weights, k=1)[0]
            pill_name = items.alchemy_pill_name("Qi Ascension", tier)
            self.db.add_item(user_id, pill_name, 1)
            results.append((name, f"1x **{pill_name}**"))
        return results

    def grant_inheritance_ground_essence_crystal_reward(self, team: list) -> list:
        """An "essence_crystal" bubble (see generate_inheritance_ground_board) -- 20-100
        Primeval Essence Crystal, independently rolled per team member, same "whole team
        shares the bubble's find" shape grant_inheritance_ground_treasure_reward uses.
        Returns [(name, reward_str), ...]."""
        results = []
        for user_id, name in team:
            qty = random.randint(*self.ESSENCE_CRYSTAL_QUANTITY_RANGE)
            self.db.add_item(user_id, "Primeval Essence Crystal", qty)
            results.append((name, f"{qty}x **Primeval Essence Crystal**"))
        return results

    def grant_inheritance_ground_essence_pill_reward(self, team: list) -> list:
        """An "essence_pill" bubble (see generate_inheritance_ground_board) -- a Tier 4-7
        Essence Restoration Pill, independently rolled per team member (tier weighted via
        items.ESSENCE_RESTORATION_PILL_TIER_WEIGHTS' own relative weights, filtered to
        [ESSENCE_PILL_MIN_TIER, ESSENCE_PILL_MAX_TIER] -- same sub-range technique treasure_
        hunt._essence_pill_tier uses). Returns [(name, reward_str), ...]."""
        sub_weights = {
            t: w for t, w in items.ESSENCE_RESTORATION_PILL_TIER_WEIGHTS.items()
            if self.ESSENCE_PILL_MIN_TIER <= t <= self.ESSENCE_PILL_MAX_TIER
        }
        tiers = list(sub_weights.keys())
        weights = list(sub_weights.values())
        results = []
        for user_id, name in team:
            tier = random.choices(tiers, weights=weights, k=1)[0]
            pill_name = items.alchemy_pill_name("Essence Restoration", tier)
            self.db.add_item(user_id, pill_name, 1)
            results.append((name, f"1x **{pill_name}**"))
        return results

    def grant_inheritance_ground_material_reward(self, team: list) -> list:
        """A "materials" bubble (2026-08-14, see generate_inheritance_ground_board) --
        guaranteed Tier 8 Herb per team member, same "whole team shares the bubble's find"
        shape every other bubble-grant function here uses. Scoped to Herb only (not also
        Ore/Beast Material/Beast Core, unlike Black Heaven's own "materials" bubble) since
        that's specifically what this bubble was added to close a gap for. Returns
        [(name, reward_str), ...]."""
        results = []
        for user_id, name in team:
            qty = random.randint(2, 5)
            self.db.add_item(user_id, "Tier 8 Herb", qty)
            results.append((name, f"{qty}x **Tier 8 Herb**"))
        return results

    def grant_inheritance_ground_immortal_notes_reward(self, team: list) -> list:
        """An "immortal_notes" bubble (2026-08-14, see generate_inheritance_ground_board) --
        guaranteed 1x Immortal Notes per team member, same "whole team shares the bubble's
        find" shape every other bubble-grant function here uses. Returns
        [(name, reward_str), ...]."""
        results = []
        for user_id, name in team:
            self.db.add_item(user_id, "Immortal Notes", 1)
            results.append((name, "1x **Immortal Notes**"))
        return results

    def grant_inheritance_ground_share_reward(self, ground_key: str, user_id: int, name: str) -> str:
        """One independent reward roll per Share-choosing member -- same "roll once per
        participant" convention raid.py's own _on_victory uses for its per-participant loot,
        rather than one shared pool awkwardly split across heterogeneous reward kinds (stones
        vs items vs pages vs a whole manual don't divide evenly). Reuses the exact
        rank/difficulty/rarity-scaled machinery /search's own inheritance discoveries use."""
        ground = inheritance_ground_data.GROUNDS[ground_key]
        rng = random.Random()
        category = discovery_gen.weighted_choice(search_data.INHERITANCE_FINAL_CHEST_TABLE, rng)
        reward = discovery_gen.generate_loot(category, "inheritance_ground", ground["gu_rank"], "Standard", ground.get("tags", []), rng)
        return self.grant_reward(user_id, name, reward)

    def roll_inheritance_ground_bonus_gu(self, ground_key: str) -> Optional[str]:
        """Rolls (but does NOT grant) the specific Core Gu item name at stake in the betrayal
        stage -- called the moment the team reaches "betrayal" (see InheritanceGroundView.
        _on_victory) so it can be REVEALED to the whole team before anyone chooses Share or
        Backstab, per explicit request ("have the group know what the core gu is so they can
        decide"). Whoever actually wins the duel is then handed this exact SAME name via
        grant_inheritance_ground_bonus_gu, so the reveal and the real prize always match --
        never re-rolled at grant time. Same rank-eligibility/weighting canon_gu.py's own
        roll_canon_gu_drop uses for WHICH family, skipping its RNG "does anything drop at all"
        gate (this must always land); quality is independently rolled "at least Epic" (see
        treasure_hunt.GU_QUALITY_WEIGHTS) per explicit request -- the backstab's real
        temptation, not a Common-tier consolation prize. Returns None only in the extremely
        unlikely case no canon Gu is eligible at this rank at all (see
        grant_inheritance_ground_bonus_gu's own fallback for that)."""
        ground = inheritance_ground_data.GROUNDS[ground_key]
        gu_rank = ground["gu_rank"]
        eligible = [
            gu for gu in canon_gu.CANON_GU
            if gu["drop_weight"] > 0 and gu["gu_rank"] in (gu_rank, max(1, gu_rank - 1))
        ]
        if not eligible:
            return None
        chosen = random.choices(eligible, weights=[gu["drop_weight"] for gu in eligible], k=1)[0]
        quality = random.choices(list(treasure_hunt.GU_QUALITY_WEIGHTS.keys()), weights=list(treasure_hunt.GU_QUALITY_WEIGHTS.values()), k=1)[0]
        return equipment.gu_item_name(chosen["name"], quality)

    def grant_inheritance_ground_bonus_gu(self, user_id: int, gu_name: Optional[str]) -> str:
        """Grants the pre-rolled Core Gu (see roll_inheritance_ground_bonus_gu) to the
        betrayal's actual winner -- a backstab winner must never end up empty-handed, so
        gu_name is None only in the extremely-unlikely "no eligible Gu at this rank" case,
        which falls back to spirit stones instead."""
        if gu_name is None:
            self.db.add_spirit_stones(user_id, 500)
            return "500 spirit stones (no matching Core Gu was found at this rank)"
        self.db.add_item(user_id, gu_name, 1)
        return gu_name

    # White Heaven's own 20 Rank 8 Unique Gu (see game/content/canon_gu_white_heaven.py) --
    # a SEPARATE roll from canon_gu.roll_canon_gu_drop's normal weighted mechanism (these 20
    # are drop_weight=0, so that roll always skips them entirely, same as the 2 pre-existing
    # Uniques). ONE combined roll per White-Heaven kill decides if ANY of the 20 drops at
    # all, not each independently -- hunt and raid get their own separate rate, each its own
    # named constant so the two can keep moving independently (raid's own higher per-attempt
    # odds are still meaningfully rarer in PRACTICE since a raid kill takes real team
    # coordination to reach, unlike hunt's much faster solo kill loop).
    WHITE_HEAVEN_HUNT_BONUS_GU_CHANCE = 1 / 3000
    WHITE_HEAVEN_RAID_BONUS_GU_CHANCE = 1 / 1000

    def roll_white_heaven_bonus_gu(self, chance: float) -> Optional[str]:
        """Called once per White-Heaven hunt kill or once per raid participant (see hunt.py's/
        raid.py's own victory handling, gated on the defeated monster's realm == "White
        Heaven", passing WHITE_HEAVEN_HUNT_BONUS_GU_CHANCE/WHITE_HEAVEN_RAID_BONUS_GU_CHANCE
        respectively). Always rolls at Common quality/star 1, same "a newly obtained Gu
        starts at 1 star" convention canon_gu.roll_canon_gu_drop uses. Returns an item_name,
        or None on a miss (by far the common case)."""
        if random.random() >= chance:
            return None
        name = random.choice(canon_gu_white_heaven.WHITE_HEAVEN_CANON_GU_NAMES)
        return equipment.gu_item_name(name, "Common")

    # -- /search_forgotten_blessed_land treasure-hunt board (see game/treasure_hunt.py) --------
    TREASURE_HUNT_REALM_GATE = 2  # Core Formation's great_realm_index
    TREASURE_HUNT_COOLDOWN_SECONDS = 1 * 3600  # 1 hour between boards, no stone/item cost

    def start_treasure_hunt(self, user_id: int, name: str):
        """Realm + cooldown gate, then rolls a fresh 25-tile board (see treasure_hunt.
        roll_board) -- returns (ok, message, board, white_heaven). board is None on refusal.
        While present in White Heaven (see white_heaven.py), the board's own rewards swap to
        the region's Tier 8/Rank 8 ceiling via treasure_hunt.grant_tile_reward's white_heaven
        flag (see TreasureHuntView) -- the realm/cooldown gate above is unaffected, since
        reaching White Heaven at all already implies clearing the (much lower) Core Formation
        gate here.

        The cooldown gate itself is routed through _check_cooldown (not a standalone elapsed-
        time calc) so it applies the same cooldown_reduction_pct discount /cd's own
        treasure_hunt_remaining already reports -- previously this used a separate raw
        calculation with no discount applied at all, so a player with ANY cooldown_reduction_
        pct source (a manual effect, Time Dao Path, ...) could see /cd say "Ready!" while this
        command still refused them with the full, undiscounted wait -- a live bug fixed
        2026-08-14."""
        player = self.db.get_or_create_player(user_id, name)
        if realms.STAGES[player["realm_index"]].great_realm_index < self.TREASURE_HUNT_REALM_GATE:
            return False, "The Forgotten Blessed Land only reveals itself to Core Formation cultivators and above.", None, False
        remaining = self._check_cooldown(player, "treasure_hunt_last_ts", self.TREASURE_HUNT_COOLDOWN_SECONDS)
        if remaining > 0:
            from .ui_utils import format_duration
            return False, f"The Blessed Land hasn't revealed a new site yet — {format_duration(remaining)} left.", None, False
        now = int(time.time())
        self.db.set_treasure_hunt_last_ts(user_id, now)
        board = treasure_hunt.roll_board()
        in_white_heaven = player["white_heaven_status"] == "present"
        if in_white_heaven:
            return True, "You uncover a sealed grotto-heaven cache, hidden since long before this realm had a name!", board, True
        return True, "You stumble into the Forgotten Blessed Land — a hidden site full of buried treasure!", board, False

    def is_avatar_unlocked(self, user_id: int, name: str) -> bool:
        player = self.db.get_or_create_player(user_id, name)
        return avatar.is_realm_eligible(realms.STAGES[player["realm_index"]].great_realm_index)

    def get_avatar_status(self, user_id: int, name: str) -> dict:
        """Single call both /avatar and /profile's Avatar tab build off."""
        player = self.db.get_or_create_player(user_id, name)
        unlocked = self.is_avatar_unlocked(user_id, name)
        soul = avatar.get_avatar_soul(player["avatar_soul"])
        equipped = self.db.get_avatar_equipped(user_id) if unlocked else {}
        return {
            "player": player, "unlocked": unlocked, "soul": soul,
            "level": player["avatar_level"], "equipped": equipped,
            "power": self.compute_avatar_power(user_id) if (unlocked and soul) else 0.0,
            "next_recipe": avatar.level_up_recipe(player["avatar_level"]),
        }

    def choose_avatar_soul(self, user_id: int, name: str, soul_name: str):
        """Direct pick from the named list (not RNG like root/physique -- the user chooses
        deliberately). Mirrors set_class's shape but made repeatable-for-a-cost instead of
        one-time: free the first time, AVATAR_SOUL_REROLL_COST spirit stones every time after."""
        player = self.db.get_or_create_player(user_id, name)
        if not self.is_avatar_unlocked(user_id, name):
            return False, "Your cultivation hasn't reached Nascent Soul realm yet."
        soul = avatar.get_avatar_soul(soul_name)
        if soul is None:
            return False, "That's not a valid avatar soul."
        if player["avatar_soul"] == soul_name:
            return False, f"Your avatar's soul is already **{soul_name}**."
        first_time = player["avatar_soul"] is None
        if not first_time and not self.db.spend_spirit_stones(user_id, self.AVATAR_SOUL_REROLL_COST):
            return False, f"Changing your avatar's soul costs **{format_number(self.AVATAR_SOUL_REROLL_COST)}** spirit stones."
        self.db.save_avatar_soul(user_id, soul_name)
        if first_time:
            self._grant_starter_avatar_gear(user_id)
        cost_note = "free — your avatar's soul awakens" if first_time else f"{format_number(self.AVATAR_SOUL_REROLL_COST)} spirit stones spent"
        return True, f"Your Nascent Soul avatar's soul is now **{soul_name}** ({cost_note})."

    def _grant_starter_avatar_gear(self, user_id: int):
        """Rolls a real Tier 1 (Formed) instance for each slot and equips it immediately --
        same bypass-inventory shape Phase 1's flat-catalog version used (never added to
        inventory first, so there's no separate ownership to desync), just with a genuine
        roll instead of a fixed item name."""
        rng = random.Random()
        for slot_key, _, slot_type, _ in avatar_gear.AVATAR_GEAR_SLOTS:
            stat_bonuses = avatar_gear.roll_avatar_gear_stats(slot_type, avatar_gear.MIN_TIER, rng)
            power_score = avatar_gear.avatar_gear_instance_power_score(stat_bonuses)
            instance_id = self.db.create_avatar_gear_instance(user_id, slot_type, avatar_gear.MIN_TIER, stat_bonuses, power_score)
            display_name = f"{avatar_gear.tier_name(avatar_gear.MIN_TIER)} {slot_type} #{instance_id}"
            self.db.set_avatar_equipped_instance(user_id, slot_key, instance_id, display_name)

    def get_avatar_equipped(self, user_id: int) -> dict:
        return self.db.get_avatar_equipped(user_id)

    def get_avatar_equipped_instance_ids(self, user_id: int) -> dict:
        return self.db.get_avatar_equipped_instance_ids(user_id)

    def get_avatar_gear_instance(self, instance_id: int) -> Optional[dict]:
        return self.db.get_avatar_gear_instance(instance_id)

    def get_player_avatar_gear_instances(self, user_id: int) -> list:
        """Every avatar gear instance this player owns (equipped or not), rarest/highest-
        power first -- mirrors get_player_accessories_artifacts' shape."""
        instances = self.db.get_player_avatar_gear_instances(user_id)
        return sorted(instances, key=lambda inst: (-inst["tier"], -inst["power_score"]))

    def sell_avatar_gear_instance(self, user_id: int, name: str, instance_id: int):
        """NPC vendor buys back an unwanted avatar gear instance for spirit stones (/sell) --
        mirrors dismantle_crafted_gear/salvage_accessory_artifact's ownership/equipped-guard/
        payout/delete skeleton. No rarity concept exists for avatar gear, so no rarity-block
        step is needed."""
        self.db.get_or_create_player(user_id, name)
        instance = self.db.get_avatar_gear_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "You don't own that item."
        if instance_id in self.db.get_avatar_equipped_instance_ids(user_id).values():
            return False, "Unequip it first before selling it."
        stones = avatar_gear.sell_stones(instance["tier"])
        self.db.add_spirit_stones(user_id, stones)
        self.db.delete_avatar_gear_instance(instance_id)
        display_name = f"{avatar_gear.tier_name(instance['tier'])} {instance['slot_type']} #{instance_id}"
        return True, f"Sold **{display_name}** for {format_number(stones)} 🪙 spirit stones."

    def roll_and_grant_avatar_gear(self, user_id: int, name: str, source_key: str, source_tier: int, slot_type: Optional[str] = None) -> dict:
        """Rolls and grants one new avatar gear instance -- does NOT auto-equip (sits owned-
        but-unequipped until the player equips it via /avatar, same as
        roll_and_grant_accessory_artifact). slot_type is picked uniformly if not given."""
        self.db.get_or_create_player(user_id, name)
        rng = random.Random()
        if slot_type is None:
            slot_type = rng.choice(list(avatar_gear.POOL_BY_SLOT_TYPE.keys()))
        tier = avatar_gear.roll_avatar_gear_tier(source_tier, rng)
        stat_bonuses = avatar_gear.roll_avatar_gear_stats(slot_type, tier, rng)
        power_score = avatar_gear.avatar_gear_instance_power_score(stat_bonuses)
        instance_id = self.db.create_avatar_gear_instance(user_id, slot_type, tier, stat_bonuses, power_score)
        return {"instance_id": instance_id, "slot_type": slot_type, "tier": tier, "stat_bonuses": stat_bonuses}

    def equip_avatar_gear_instance(self, user_id: int, name: str, slot_key: str, instance_id: int):
        """Mirrors equip_accessory_artifact's displacement logic. One avatar-gear-specific
        edge case: a slot can still hold a legacy Phase-1 flat catalog item (instance_id
        NULL) -- that item IS a real inventory row (unlike new instances, which aren't
        inventory-backed at all), so displacing it must return it to inventory or it
        silently vanishes."""
        self.db.get_or_create_player(user_id, name)
        expected_type = avatar_gear.SLOT_TYPE_BY_KEY.get(slot_key)
        if expected_type is None:
            return False, "That avatar slot doesn't exist."
        instance = self.db.get_avatar_gear_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "You don't own that item."
        if instance["slot_type"] != expected_type:
            return False, f"That item doesn't fit in the avatar's {avatar_gear.SLOT_LABEL_BY_KEY[slot_key]} slot."

        equipped_instance_ids = self.db.get_avatar_equipped_instance_ids(user_id)
        if equipped_instance_ids.get(slot_key) == instance_id:
            return False, "That item is already equipped there."

        if slot_key not in equipped_instance_ids:
            previous_item_name = self.db.get_avatar_equipped(user_id).get(slot_key)
            if previous_item_name and previous_item_name in avatar_gear.AVATAR_GEAR:
                self.db.add_item(user_id, previous_item_name, 1)

        display_name = f"{avatar_gear.tier_name(instance['tier'])} {instance['slot_type']} #{instance_id}"
        self.db.set_avatar_equipped_instance(user_id, slot_key, instance_id, display_name)
        return True, f"Equipped **{display_name}** to your avatar's {avatar_gear.SLOT_LABEL_BY_KEY[slot_key]}."

    def unequip_avatar_gear_instance(self, user_id: int, name: str, slot_key: str):
        self.db.get_or_create_player(user_id, name)
        item_name = self.db.get_avatar_equipped(user_id).get(slot_key)
        if not item_name:
            return False, "That avatar slot is already empty."
        # Ownership always persists in avatar_gear_instances regardless of equip state, so
        # there's nothing to "return" for an instance -- only a legacy catalog item needs
        # its inventory row given back.
        if item_name in avatar_gear.AVATAR_GEAR:
            self.db.add_item(user_id, item_name, 1)
        self.db.clear_avatar_equipped(user_id, slot_key)
        return True, f"Unequipped **{item_name}** from your avatar's {avatar_gear.SLOT_LABEL_BY_KEY[slot_key]}."

    def _avatar_gear_power(self, user_id: int) -> float:
        """Sums equipped avatar gear's power score -- new rolled instances read their own
        stored power_score; any surviving Phase-1 legacy flat item (instance_id NULL) falls
        back to the old avatar_offense/defense/utility scoring so it still contributes
        SOMETHING rather than erroring or silently zeroing out."""
        equipped = self.db.get_avatar_equipped(user_id)
        instance_ids = self.db.get_avatar_equipped_instance_ids(user_id)
        total = 0.0
        for slot_key, item_name in equipped.items():
            if slot_key in instance_ids:
                instance = self.db.get_avatar_gear_instance(instance_ids[slot_key])
                if instance:
                    total += instance["power_score"]
            elif item_name in avatar_gear.AVATAR_GEAR:
                total += avatar_gear.legacy_avatar_gear_power_score(avatar_gear.AVATAR_GEAR[item_name])
        return total

    def compute_avatar_power(self, user_id: int) -> float:
        """Level contribution + equipped avatar gear's power score, summed -- a descriptive
        "how strong is my avatar" number shown in /avatar and /profile. Also the input
        soul_projection_multiplier below scales off, so equipping better avatar gear has a
        real combat payoff."""
        player = self.db.get_player_row(user_id)
        if not player:
            return 0.0
        base = 100 * avatar.AVATAR_LEVEL_MULTIPLIER.get(player["avatar_level"], 1.0)
        return round(base + self._avatar_gear_power(user_id), 1)

    def soul_projection_multiplier(self, user_id: int) -> float:
        """How much stronger Soul Projection's temporary bonus is than its passive baseline
        (see avatar.soul_projection_bonus) -- scales with equipped avatar gear power, a Soul
        Path Soul wielder's own avatar_power_pct passive, and now avatar gear's own
        soul_projection_damage_pct/soul_skill_potency_pct rolls. 1.0 (no amplification at
        all) if no soul is chosen. Computes its own compute_equipment_bonuses call rather
        than taking one as a parameter -- this codebase already tolerates a redundant
        per-swing compute_equipment_bonuses call elsewhere (e.g. hunt.py's
        _monster_turn + _player_combat_stats each compute their own), and it's a local
        SQLite read, not a network call."""
        player = self.db.get_player_row(user_id)
        if not player or not player["avatar_soul"]:
            return 1.0
        gear_bonus_pct = self._avatar_gear_power(user_id) / 100.0
        soul_path_bonus = avatar.scaled_bonus(player["avatar_soul"], player["avatar_level"], "avatar_power_pct")
        bonuses = self.compute_equipment_bonuses(user_id)
        gear_stat_bonus = bonuses.get("soul_projection_damage_pct", 0) + bonuses.get("soul_skill_potency_pct", 0)
        return avatar.SOUL_PROJECTION_BASE_MULTIPLIER * (1 + gear_bonus_pct + soul_path_bonus + gear_stat_bonus)

    def avatar_level_up(self, user_id: int, name: str):
        """Feeds the exact recipe for the next level in one shot -- no partial-progress
        state (see avatar.AVATAR_LEVEL_UP_RECIPE's own docstring for why)."""
        player = self.db.get_or_create_player(user_id, name)
        if player["avatar_soul"] is None:
            return False, "Choose your avatar's soul with `/avatar` first."
        recipe = avatar.level_up_recipe(player["avatar_level"])
        if recipe is None:
            return False, "Your avatar is already at its peak — Level X."
        inventory = self.db.get_inventory(user_id)
        if any(inventory.get(item, 0) < qty for item, qty in recipe.items()):
            return False, "Not enough Soul Nourishing Pills / Soul Crystals for the next level."
        for item, qty in recipe.items():
            self.db.remove_item(user_id, item, qty)
        new_level = self.db.set_avatar_level(user_id, player["avatar_level"] + 1)
        return True, f"Your Nascent Soul avatar advances to Level **{avatar.level_name(new_level)}**!"

    # -- /split_body: the avatar's own timed loot mission (see game/split_body.py) ----------
    # Single-pending-job shape, deliberately mirroring study()/cancel_study() above.

    SPLIT_BODY_MANUAL_PAGE_CHANCE = 0.12

    def progress_split_body(self, user_id: int, name: str) -> dict:
        """Advances the avatar's Split Body mission state one step -- outcome is one of:
          "no_soul"     — defensive re-check; the /split_body command itself already gates on
                          a soul being chosen before this is ever called.
          "started"     — began the mission (nothing was in progress).
          "in_progress" — already out searching, not back yet.
          "claimed"     — mission was ready; loot rolled, granted, and mission cleared.
        """
        player = self.db.get_or_create_player(user_id, name)
        if player["avatar_soul"] is None:
            return {"outcome": "no_soul"}

        if player["split_body_started_ts"] == 0:
            self.db.start_split_body(user_id)
            return {"outcome": "started"}

        elapsed_seconds = time.time() - player["split_body_started_ts"]
        if elapsed_seconds < split_body.SPLIT_BODY_DURATION_SECONDS:
            return {
                "outcome": "in_progress",
                "elapsed_seconds": elapsed_seconds,
                "remaining_seconds": split_body.SPLIT_BODY_DURATION_SECONDS - elapsed_seconds,
            }

        tier = self._player_location_rank(player)
        loot = split_body.roll_split_body_loot(tier, player["avatar_level"])
        for item_name, quantity in loot.items():
            self.db.add_item(user_id, item_name, quantity)
        accessory = self.roll_and_grant_accessory_artifact(user_id, name, "split_body", tier, [])
        pages = discovery_gen._roll_pages(tier, 1, [], random.Random()) if random.random() < self.SPLIT_BODY_MANUAL_PAGE_CHANCE else []
        for page_id in pages:
            self.db.add_player_page(user_id, page_id, 1)
        self.db.clear_split_body(user_id)
        return {"outcome": "claimed", "loot": loot, "accessory": accessory, "pages": pages}

    def get_ready_split_body_players(self) -> list:
        """Read-only, used only by the background DM tick (cog.py's split_body_tick) -- never
        clears split_body_started_ts itself (claiming is a deliberate player action via
        progress_split_body, not something a scheduled scan does on their behalf)."""
        return [
            player for player in self.db.get_players_with_unnotified_split_body()
            if time.time() - player["split_body_started_ts"] >= split_body.SPLIT_BODY_DURATION_SECONDS
        ]

    # -- Grotto (see game/grotto.py / /grotto) -----------------------------------------------

    def get_grotto_status(self, user_id: int, name: str) -> dict:
        """Read-only -- for /grotto's view to show current level, live bonuses, and the next
        upgrade's cost without spending anything."""
        player = self.db.get_or_create_player(user_id, name)
        level = player["grotto_level"]
        eligible = grotto.is_realm_eligible(realms.STAGES[player["realm_index"]].great_realm_index)
        recipe = grotto.level_up_recipe(level)
        return {
            "level": level,
            "eligible": eligible,
            "bonuses": grotto.grotto_bonuses(level),
            "next_recipe": recipe,
            "next_stones_cost": grotto.level_up_stones_cost(level + 1) if recipe is not None else None,
            "maxed": recipe is None,
        }

    def upgrade_grotto(self, user_id: int, name: str):
        """Founds the grotto (level 0 -> 1) or advances it one level, atomically -- same
        exact-recipe-per-level shape as avatar_level_up, plus a separate spirit-stone cost
        (see grotto.level_up_stones_cost's own docstring for why that's not folded into the
        same materials recipe dict)."""
        player = self.db.get_or_create_player(user_id, name)
        if not grotto.is_realm_eligible(realms.STAGES[player["realm_index"]].great_realm_index):
            return False, "Your grotto awakens once you reach **Foundation Establishment** — keep cultivating!"
        recipe = grotto.level_up_recipe(player["grotto_level"])
        if recipe is None:
            return False, f"Your grotto is already at its peak — Level {grotto.GROTTO_MAX_LEVEL}."
        stones_cost = grotto.level_up_stones_cost(player["grotto_level"] + 1)
        if player["spirit_stones"] < stones_cost:
            return False, f"Not enough spirit stones — need {format_number(stones_cost)}, have {format_number(player['spirit_stones'])}."
        inventory = self.db.get_inventory(user_id)
        missing = {item: qty for item, qty in recipe.items() if inventory.get(item, 0) < qty}
        if missing:
            missing_text = ", ".join(f"{qty}x {item} (have {inventory.get(item, 0)})" for item, qty in missing.items())
            return False, f"Missing materials: {missing_text}."
        if not self.db.spend_spirit_stones(user_id, stones_cost):
            return False, "Not enough spirit stones."  # defensive re-check, shouldn't fire after the check above
        for item, qty in recipe.items():
            self.db.remove_item(user_id, item, qty)
        new_level = self.db.set_grotto_level(user_id, player["grotto_level"] + 1)
        verb = "founded" if new_level == 1 else "deepened"
        return True, f"Your grotto is {verb} — now **Level {new_level}**!"

    def _grotto_yield_bonus(self, player: dict) -> float:
        """Grotto's flat mine/gather/farm yield bonus -- mirrors _trait_bonus's own shape but
        reads grotto_level directly, since mine/gather/farm have no generic bonus pool at all
        (each computes its own yield_mult independently -- see start_mining_vein/
        start_gathering_patch/harvest_farm)."""
        return grotto.grotto_bonuses(player["grotto_level"]).get("grotto_yield_pct", 0.0)

    def get_crafting_success_bonus_total(self, user_id: int) -> float:
        """Every non-rank source of /blacksmith craft success -- Space Dao Path plus Grotto --
        summed in ONE place so craft_gear and blacksmith_view's own preview can never drift
        apart (they previously each independently re-derived just the Dao Path half of this)."""
        player = self.db.get_player_row(user_id)
        space_bonus = self.get_dao_path_totals(user_id).get("crafting_success_pct", 0)
        grotto_bonus = grotto.grotto_bonuses(player["grotto_level"]).get("grotto_crafting_success_pct", 0.0) if player else 0.0
        return space_bonus + grotto_bonus

    # -- Ink Men (see game/grotto.py / /grotto) -- passively work through owned manual-page
    # duplicates by calling the EXISTING refine_page on the player's behalf, no reimplemented
    # refinement logic. ---------------------------------------------------------------------

    def recruit_ink_man(self, user_id: int, name: str):
        player = self.db.get_or_create_player(user_id, name)
        if player["grotto_level"] <= 0:
            return False, "Found your grotto with `/grotto` first."
        owned = len(self.db.get_player_ink_men(user_id))
        if owned >= grotto.GROTTO_MAX_INK_MEN:
            return False, f"You already have the maximum {grotto.GROTTO_MAX_INK_MEN} Ink Men."
        stones_cost = grotto.ink_man_recruit_stones_cost(owned)
        ink_cost = grotto.ink_man_recruit_ink_cost(owned)
        dust_cost = grotto.ink_man_recruit_dust_cost(owned)
        if player["spirit_stones"] < stones_cost or player["manual_ink"] < ink_cost or player["insight_dust"] < dust_cost:
            return False, (
                f"Not enough resources — need {format_number(stones_cost)} spirit stones, "
                f"{format_number(ink_cost)} Manual Ink, {format_number(dust_cost)} Insight Dust."
            )
        if not self.db.spend_spirit_stones(user_id, stones_cost):
            return False, "Not enough spirit stones."
        self.db.spend_manual_ink(user_id, ink_cost)
        self.db.spend_insight_dust(user_id, dust_cost)
        self.db.create_ink_man(user_id)
        return True, "An Ink Man arrives at your grotto, ready to work."

    def assign_ink_man(self, user_id: int, ink_man_id: int, page_id: str):
        ink_man = self.db.get_ink_man(ink_man_id)
        if ink_man is None or ink_man["owner_id"] != user_id:
            return False, "That Ink Man isn't yours."
        if ink_man["assigned_page_id"] is not None:
            return False, "That Ink Man is already working on something."
        owned_pages = self.db.get_player_pages(user_id)
        owned = owned_pages.get(page_id)
        if not owned:
            return False, "You don't own that page."
        page = manual_data.PAGES.get(page_id)
        if page is None:
            return False, "That isn't a real page."
        if manual_data.NEXT_REFINEMENT.get(owned["refinement_level"]) is None:
            return False, f"**{page.name}** is already at the highest refinement level."
        self.db.assign_ink_man_page(ink_man_id, page_id, int(time.time()) + grotto.INK_MAN_TICK_INTERVAL_SECONDS)
        return True, f"Your Ink Man begins refining **{page.name}**."

    def get_ink_men_status(self, user_id: int) -> list:
        """Read-only -- for /grotto's Ink Men tab."""
        result = []
        for ink_man in self.db.get_player_ink_men(user_id):
            page = manual_data.PAGES.get(ink_man["assigned_page_id"]) if ink_man["assigned_page_id"] else None
            result.append({
                "ink_man_id": ink_man["ink_man_id"], "assigned_page_id": ink_man["assigned_page_id"],
                "page_name": page.name if page else None, "idle": ink_man["assigned_page_id"] is None,
                "next_tick_ts": ink_man["next_tick_ts"],
            })
        return result

    def check_and_complete_ink_men_work(self) -> list:
        """Periodic sweep (see cog.py's grotto_tick) -- for every Ink Man whose next tick has
        elapsed, calls the EXISTING refine_page on the player's behalf. On success, keeps
        grinding the same page (resets the timer); on failure (maxed out, or ran out of
        duplicates), goes idle. Returns one summary dict per Ink Man that did something, for
        the caller to DM about."""
        completed = []
        now = int(time.time())
        for ink_man in self.db.get_ink_men_pending_work(now):
            owner_id = ink_man["owner_id"]
            player = self.db.get_player_row(owner_id)
            if player is None:
                self.db.clear_ink_man_assignment(ink_man["ink_man_id"])
                continue
            page_id = ink_man["assigned_page_id"]
            ok, message = self.refine_page(owner_id, player["name"], page_id)
            if ok:
                self.db.set_ink_man_next_tick(ink_man["ink_man_id"], now + grotto.INK_MAN_TICK_INTERVAL_SECONDS)
            else:
                self.db.clear_ink_man_assignment(ink_man["ink_man_id"])
            completed.append({"user_id": owner_id, "name": player["name"], "success": ok, "message": message})
        return completed

    # -- Hairy Men (see game/grotto.py / /grotto) -- passively bless ONE specific Legendary+
    # Gu instance over time. -------------------------------------------------------------------

    def recruit_hairy_man(self, user_id: int, name: str):
        player = self.db.get_or_create_player(user_id, name)
        if player["grotto_level"] <= 0:
            return False, "Found your grotto with `/grotto` first."
        owned = len(self.db.get_player_hairy_men(user_id))
        if owned >= grotto.GROTTO_MAX_HAIRY_MEN:
            return False, f"You already have the maximum {grotto.GROTTO_MAX_HAIRY_MEN} Hairy Men."
        stones_cost = grotto.hairy_man_recruit_stones_cost(owned)
        recipe = grotto.hairy_man_recruit_recipe(owned)
        if player["spirit_stones"] < stones_cost:
            return False, f"Not enough spirit stones — need {format_number(stones_cost)}."
        inventory = self.db.get_inventory(user_id)
        missing = {item: qty for item, qty in recipe.items() if inventory.get(item, 0) < qty}
        if missing:
            missing_text = ", ".join(f"{qty}x {item} (have {inventory.get(item, 0)})" for item, qty in missing.items())
            return False, f"Missing materials: {missing_text}."
        if not self.db.spend_spirit_stones(user_id, stones_cost):
            return False, "Not enough spirit stones."
        for item, qty in recipe.items():
            self.db.remove_item(user_id, item, qty)
        self.db.create_hairy_man(user_id)
        return True, "A Hairy Man arrives at your grotto, ready to work."

    def assign_hairy_man(self, user_id: int, hairy_man_id: int, item_name: str):
        hairy_man = self.db.get_hairy_man(hairy_man_id)
        if hairy_man is None or hairy_man["owner_id"] != user_id:
            return False, "That Hairy Man isn't yours."
        if hairy_man["assigned_instance_id"] is not None:
            return False, "That Hairy Man is already working on something."
        quality = equipment.gu_quality_for(item_name)
        if quality not in grotto.GU_LEGENDARY_PLUS_QUALITIES:
            return False, "Only Legendary, Mythic, or Immortal Gu can be blessed."
        if self.db.get_inventory(user_id).get(item_name, 0) < 1:
            return False, f"You don't own **{item_name}**."
        if not self.db.remove_item(user_id, item_name, 1):
            return False, f"You don't own **{item_name}**."
        instance_id = self.db.create_gu_instance(user_id, item_name)
        self.db.assign_hairy_man_instance(hairy_man_id, instance_id, int(time.time()) + grotto.HAIRY_MAN_TICK_INTERVAL_SECONDS)
        return True, f"Your Hairy Man begins blessing **{item_name}**."

    def cancel_hairy_man_work(self, user_id: int, hairy_man_id: int):
        """Stops an in-progress blessing early -- the Gu instance keeps whatever bonus it's
        already accrued (it's already a real, equippable item the moment assign_hairy_man
        converts it, same as a fully-blessed one), it just stops gaining any more. Nothing is
        refunded, mirroring cancel_study's own "invested time isn't given back" precedent --
        there's no existing mechanism anywhere in this codebase to un-consume the original item
        assign_hairy_man spent. Frees the Hairy Man to be assigned to a different Gu."""
        hairy_man = self.db.get_hairy_man(hairy_man_id)
        if hairy_man is None or hairy_man["owner_id"] != user_id:
            return False, "That Hairy Man isn't yours."
        if hairy_man["assigned_instance_id"] is None:
            return False, "That Hairy Man isn't working on anything."
        instance = self.db.get_gu_instance(hairy_man["assigned_instance_id"])
        item_name = instance["item_name"] if instance else "the Gu"
        self.db.clear_hairy_man_assignment(hairy_man_id)
        return True, f"Your Hairy Man stops blessing **{item_name}** — it keeps its current bonus, and your Hairy Man is free to work on something else."

    def get_hairy_men_status(self, user_id: int) -> list:
        """Read-only -- for /grotto's Hairy Men tab."""
        result = []
        for hairy_man in self.db.get_player_hairy_men(user_id):
            instance = self.db.get_gu_instance(hairy_man["assigned_instance_id"]) if hairy_man["assigned_instance_id"] else None
            result.append({
                "hairy_man_id": hairy_man["hairy_man_id"], "assigned_instance_id": hairy_man["assigned_instance_id"],
                "item_name": instance["item_name"] if instance else None,
                "blessing_ticks": instance["blessing_ticks"] if instance else 0,
                "idle": hairy_man["assigned_instance_id"] is None, "next_tick_ts": hairy_man["next_tick_ts"],
            })
        return result

    def check_and_complete_hairy_men_work(self) -> list:
        """Periodic sweep (see cog.py's grotto_tick) -- for every Hairy Man whose next tick
        has elapsed, deepens the blessing on their assigned Gu instance by one tick. Goes idle
        once GROTTO_BLESSING_MAX_TICKS is reached ('fully blessed'). Returns one summary dict
        per Hairy Man that did something, for the caller to DM about."""
        completed = []
        now = int(time.time())
        for hairy_man in self.db.get_hairy_men_pending_work(now):
            owner_id = hairy_man["owner_id"]
            player = self.db.get_player_row(owner_id)
            instance = self.db.get_gu_instance(hairy_man["assigned_instance_id"])
            if player is None or instance is None:
                self.db.clear_hairy_man_assignment(hairy_man["hairy_man_id"])
                continue
            base_gear = equipment.EQUIPMENT.get(instance["item_name"])
            base_stat_bonuses = base_gear.stat_bonuses if base_gear else {}
            new_ticks = instance["blessing_ticks"] + 1
            new_bonus = grotto.blessing_bonus_stat_bonuses(base_stat_bonuses, new_ticks)
            self.db.update_gu_instance_blessing(instance["instance_id"], new_ticks, new_bonus)
            maxed = new_ticks >= grotto.GROTTO_BLESSING_MAX_TICKS
            if maxed:
                self.db.clear_hairy_man_assignment(hairy_man["hairy_man_id"])
                message = f"**{instance['item_name']}** is now fully blessed!"
            else:
                self.db.set_hairy_man_next_tick(hairy_man["hairy_man_id"], now + grotto.HAIRY_MAN_TICK_INTERVAL_SECONDS)
                message = f"Your Hairy Man deepens the blessing on **{instance['item_name']}** ({new_ticks}/{grotto.GROTTO_BLESSING_MAX_TICKS})."
            completed.append({"user_id": owner_id, "name": player["name"], "item_name": instance["item_name"], "message": message, "maxed": maxed})
        return completed

    # -- Servants (see game/servants.py / /servant) ----------------------

    def summon_servant(self, user_id: int, currency: str, count: int = 1):
        """Rolls `count` servants, paid for via one of servants.SUMMON_CURRENCIES (alternatives,
        not a simultaneous multi-currency cost). Spends atomically BEFORE any roll happens --
        refuses outright if funds are short, never a partial deduction. Returns
        (ok, message, rolled) where rolled is a list of (name, tier) tuples."""
        if currency not in servants.SUMMON_CURRENCIES:
            return False, "Not a valid currency.", []
        unit_cost = servants.SUMMON_CURRENCY_COST[currency]
        total_cost = unit_cost * count
        if currency == servants.CURRENCY_STONES:
            if not self.db.spend_spirit_stones(user_id, total_cost):
                return False, f"Not enough spirit stones — need {format_number(total_cost)}.", []
        elif currency == servants.CURRENCY_ESSENCE_CRYSTALS:
            if not self.db.remove_item(user_id, servants.PRIMEVAL_ESSENCE_CRYSTAL, total_cost):
                return False, f"Not enough Primeval Essence Crystals — need {total_cost}.", []
        else:  # beast_cores
            if not self.db.spend_beast_cores_any_tier(user_id, total_cost):
                return False, f"Not enough Beast Cores (any tier) — need {total_cost}.", []
        rolled = []
        for _ in range(count):
            name = servants.roll_servant()
            servant = servants.SERVANT_CATALOG[name]
            self.db.create_servant_instance(user_id, name, servant.tier)
            rolled.append((name, servant.tier))
        return True, f"Summoned {count} servant(s)!", rolled

    def get_player_servants(self, user_id: int) -> list:
        """Read-only -- for /servant's Roster/Star Up/Equip tabs. Each instance dict gets a
        live "current_affinity_seconds" (see servants.current_affinity_seconds) folded in for
        display, without mutating the persisted value."""
        now = int(time.time())
        instances = self.db.get_player_servant_instances(user_id)
        for instance in instances:
            instance["current_affinity_seconds"] = servants.current_affinity_seconds(instance, now)
        return instances

    def get_equipped_servants(self, user_id: int) -> dict:
        """Read-only -- {servants.SLOT_KEY_SUPPORT/SLOT_KEY_COMBAT: instance dict or None} for
        /servant's Equip tab. Each present instance gets a live "current_affinity_seconds"
        folded in, same as get_player_servants."""
        now = int(time.time())
        equipped_ids = self.db.get_equipped_servant_instance_ids(user_id)
        result = {}
        for slot_key in servants.SERVANT_SLOT_KEYS:
            instance = self.db.get_servant_instance(equipped_ids[slot_key]) if slot_key in equipped_ids else None
            if instance:
                instance["current_affinity_seconds"] = servants.current_affinity_seconds(instance, now)
            result[slot_key] = instance
        return result

    def get_servant_collection_bonus_pct(self, user_id: int) -> float:
        """Read-only -- for /servant's Roster tab header."""
        return servants.collection_bonus_pct(self.db.count_distinct_servant_names(user_id))

    def star_up_servant(self, user_id: int, keep_instance_id: int, consume_instance_ids: list):
        """Consumes exact-name duplicates as fuel to advance keep's star level by one -- keep's
        own instance_id (and therefore its equip/automation state) never changes. See
        servants.STAR_UP_DUPLICATES_REQUIRED."""
        keep = self.db.get_servant_instance(keep_instance_id)
        if keep is None or keep["owner_id"] != user_id:
            return False, "That servant isn't yours."
        if keep["star_level"] >= servants.MAX_STAR_LEVEL:
            return False, f"**{keep['name']}** is already at the maximum star level."
        required = servants.STAR_UP_DUPLICATES_REQUIRED[keep["star_level"]]
        if len(consume_instance_ids) != required:
            return False, f"Star-up from ★{keep['star_level']} needs exactly {required} duplicate(s)."
        consumed = []
        for instance_id in consume_instance_ids:
            if instance_id == keep_instance_id:
                return False, "Can't consume the servant you're starring up."
            instance = self.db.get_servant_instance(instance_id)
            if instance is None or instance["owner_id"] != user_id:
                return False, "One of those duplicates isn't yours."
            if instance["name"] != keep["name"]:
                return False, f"One of those duplicates isn't **{keep['name']}**."
            consumed.append(instance)
        for instance in consumed:
            self.db.delete_servant_instance(instance["instance_id"])
        new_star = keep["star_level"] + 1
        self.db.set_servant_instance_star(keep_instance_id, new_star)
        return True, f"**{keep['name']}** advances to ★{new_star}!"

    def star_up_all(self, user_id: int, keep_instance_id: int):
        """One-click bulk version of star_up_servant -- repeatedly stars up keep_instance_id
        using currently-owned exact-name duplicates, advancing as many star levels as available
        dupes allow right now. Reuses star_up_servant's own validation/consumption for each
        individual step (one source of truth), so it stops cleanly at MAX_STAR_LEVEL or the
        first step it can't afford."""
        stars_gained = 0
        while True:
            keep = self.db.get_servant_instance(keep_instance_id)
            if keep is None or keep["owner_id"] != user_id:
                return False, "That servant isn't yours."
            if keep["star_level"] >= servants.MAX_STAR_LEVEL:
                break
            required = servants.STAR_UP_DUPLICATES_REQUIRED[keep["star_level"]]
            dupes = [
                i for i in self.db.get_player_servant_instances(user_id)
                if i["name"] == keep["name"] and i["instance_id"] != keep_instance_id
            ]
            if len(dupes) < required:
                break
            consume_ids = [d["instance_id"] for d in dupes[:required]]
            ok, _ = self.star_up_servant(user_id, keep_instance_id, consume_ids)
            if not ok:
                break
            stars_gained += 1
        if stars_gained == 0:
            return False, "Not enough duplicates for even one more star-up."
        final = self.db.get_servant_instance(keep_instance_id)
        return True, f"**{final['name']}** advances {stars_gained} star(s) to ★{final['star_level']}!"

    def evolve_servant(self, user_id: int, instance_id: int):
        """A maxed (★7) T5/T6 servant evolves into a freshly-rolled T6/T7 named servant -- a
        full identity swap (see servants.roll_named_servant), not a fixed mapping. star_level
        intentionally resets to 1 (a fresh copy of the new identity), but Level and Affinity --
        player-invested resources/bond time, not part of the servant's raw identity -- carry
        forward onto the new instance, same as equip/automation state. Returns (ok, message,
        new_instance_id) -- new_instance_id is None on failure, otherwise the freshly-created
        row's id, so a caller (see servant_view.ServantView._on_evolve) can immediately select
        and display exactly what the servant evolved into."""
        instance = self.db.get_servant_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "That servant isn't yours.", None
        if not servants.can_evolve(instance["tier"], instance["star_level"]):
            return False, f"**{instance['name']}** can't evolve yet — needs to be ★{servants.MAX_STAR_LEVEL} at Tier 5 or 6.", None
        new_tier = instance["tier"] + 1
        new_name = servants.roll_named_servant(new_tier)

        equipped_slot_key = None
        for slot_key, equipped_instance_id in self.db.get_equipped_servant_instance_ids(user_id).items():
            if equipped_instance_id == instance_id:
                equipped_slot_key = slot_key
                break
        was_automated = instance["automation_duty"]
        automation_next_tick_ts = instance["automation_next_tick_ts"]

        now = int(time.time())
        if equipped_slot_key:
            # Settle BEFORE deleting -- the old row is about to disappear, so its live elapsed
            # equipped-time has to be folded into affinity_seconds now or it's lost.
            self.db.settle_servant_affinity(instance_id, now)
            instance = self.db.get_servant_instance(instance_id)

        old_name = instance["name"]
        self.db.delete_servant_instance(instance_id)
        new_instance_id = self.db.create_servant_instance(
            user_id, new_name, new_tier, star_level=1, level=instance["level"], affinity_seconds=instance["affinity_seconds"],
        )
        if equipped_slot_key:
            self.db.set_equipped_servant(user_id, equipped_slot_key, new_instance_id, new_name)
            self.db.start_servant_affinity(new_instance_id, now)  # continues accruing, no gap
        if was_automated:
            self.db.set_servant_automation(new_instance_id, was_automated, automation_next_tick_ts)

        return True, f"**{old_name}** evolves into **{new_name}** (Tier {new_tier})!", new_instance_id

    def equip_servant(self, user_id: int, slot_key: str, instance_id: int):
        if slot_key not in servants.SERVANT_SLOT_KEYS:
            return False, "Not a valid servant slot."
        instance = self.db.get_servant_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "That servant isn't yours."
        now = int(time.time())
        previous_id = self.db.get_equipped_servant_instance_ids(user_id).get(slot_key)
        if previous_id and previous_id != instance_id:
            self.db.settle_servant_affinity(previous_id, now)  # displaced servant stops accruing
        self.db.set_equipped_servant(user_id, slot_key, instance_id, instance["name"])
        self.db.start_servant_affinity(instance_id, now)
        slot_label = "Combat" if slot_key == servants.SLOT_KEY_COMBAT else "Support"
        return True, f"**{instance['name']}** equipped to {slot_label}."

    def unequip_servant(self, user_id: int, slot_key: str):
        if slot_key not in servants.SERVANT_SLOT_KEYS:
            return False, "Not a valid servant slot."
        instance_id = self.db.get_equipped_servant_instance_ids(user_id).get(slot_key)
        if instance_id:
            self.db.settle_servant_affinity(instance_id, int(time.time()))
        self.db.clear_equipped(user_id, slot_key)
        return True, "Servant unequipped."

    def level_up_servant(self, user_id: int, instance_id: int):
        """Feeds Soul Nourishing Pill + Soul Crystal + spirit stones to advance a servant's
        Level by one -- independent of Star (duplicates) and Tier (evolution), so it progresses
        even a single dupe-less copy. See servants.level_up_recipe/level_up_stones_cost."""
        instance = self.db.get_servant_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "That servant isn't yours."
        recipe = servants.level_up_recipe(instance["tier"], instance["level"])
        if recipe is None:
            return False, f"**{instance['name']}** is already at the maximum level."
        stones_cost = servants.level_up_stones_cost(instance["tier"], instance["level"])
        player = self.db.get_player_row(user_id)
        if player["spirit_stones"] < stones_cost:
            return False, f"Not enough spirit stones — need {format_number(stones_cost)}."
        inventory = self.db.get_inventory(user_id)
        missing = {item: qty for item, qty in recipe.items() if inventory.get(item, 0) < qty}
        if missing:
            missing_text = ", ".join(f"{qty}x {item} (have {inventory.get(item, 0)})" for item, qty in missing.items())
            return False, f"Missing materials: {missing_text}."
        if not self.db.spend_spirit_stones(user_id, stones_cost):
            return False, "Not enough spirit stones."
        for item, qty in recipe.items():
            self.db.remove_item(user_id, item, qty)
        new_level = instance["level"] + 1
        self.db.set_servant_instance_level(instance_id, new_level)
        return True, f"**{instance['name']}** advances to Level {new_level}!"

    def assign_servant_duty(self, user_id: int, instance_id: int, duty: str):
        if duty not in servants.AUTOMATION_DUTIES:
            return False, "Not a valid duty."
        instance = self.db.get_servant_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "That servant isn't yours."
        if instance["automation_duty"] is not None:
            return False, f"**{instance['name']}** is already on duty."
        if self.db.count_player_automated_servants(user_id) >= servants.MAX_AUTOMATION_SERVANTS:
            return False, f"You already have the maximum {servants.MAX_AUTOMATION_SERVANTS} servants on automation duty."
        next_tick_ts = int(time.time()) + servants.AUTOMATION_TICK_INTERVAL_SECONDS
        self.db.set_servant_automation(instance_id, duty, next_tick_ts)
        return True, f"**{instance['name']}** begins working the {duty} duty."

    def unassign_servant_duty(self, user_id: int, instance_id: int):
        instance = self.db.get_servant_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "That servant isn't yours."
        self.db.clear_servant_automation(instance_id)
        return True, f"**{instance['name']}** stops working."

    @staticmethod
    def _sum_node_quantities(nodes: list) -> dict:
        """Sums a mine/gather roll's nodes by item_name -- MINE_VEIN_NODE_COUNT/GATHER_PATCH_
        NODE_COUNT nodes are rolled independently, so two nodes landing on the same tier (and
        therefore the same item_name) is common; a bare {item_name: quantity for node in nodes}
        dict comprehension silently DROPS the earlier duplicate's quantity instead of adding it
        (the exact bug this helper replaces -- MiningVeinView's own self.collected accumulates
        the same way, see mining_view.py's _on_strike)."""
        collected: dict = {}
        for node in nodes:
            collected[node["item_name"]] = collected.get(node["item_name"], 0) + node["quantity"]
        return collected

    def check_and_complete_servant_automation(self) -> list:
        """Periodic sweep (see cog.py's servant_automation_tick) -- for every servant whose
        automation_next_tick_ts has elapsed, calls the EXISTING start_mining_vein/
        start_gathering_patch/harvest_all_farm on the player's behalf (no reimplemented yield
        logic), then scales the result up by the ASSIGNED servant's own automation_yield_bonus_pct
        (tier/star/level/affinity -- see servants.automation_yield_bonus_pct) so a higher-tier,
        more-invested servant is a meaningfully better automated worker, not just eligible to
        work at all. Always reschedules for another attempt, win or miss -- unlike Ink Men running
        out of page duplicates, a mine/gather/farm cycle is always eventually available again, so a
        servant never goes idle here (a same-cycle collision with the player's own manual /mine
        or /gather is rare and harmless: MINE/GATHER_COOLDOWN_SECONDS are both 900, dwarfed by
        the 24h tick interval, so it just skips to next cycle). Farm duty is harvest-only in this
        pass -- it does not auto-replant emptied plots (see servants.py's own module comment)."""
        completed = []
        now = int(time.time())
        for instance in self.db.get_servant_automation_pending(now):
            owner_id = instance["owner_id"]
            player = self.db.get_player_row(owner_id)
            if player is None:
                self.db.clear_servant_automation(instance["instance_id"])
                continue
            duty = instance["automation_duty"]
            servant = servants.SERVANT_CATALOG.get(instance["name"])
            affinity = servants.current_affinity_seconds(instance, now)
            bonus_pct = servants.automation_yield_bonus_pct(servant, instance["star_level"], instance["level"], affinity) if servant else 0.0
            success = False
            if duty == servants.DUTY_MINE:
                result = self.start_mining_vein(owner_id, player["name"])
                if result["ok"]:
                    collected = self._sum_node_quantities(result["nodes"])
                    boosted = {item: round(qty * (1 + bonus_pct)) for item, qty in collected.items()}
                    self.collect_mining_vein(owner_id, boosted)
                    for item, qty in boosted.items():
                        self.db.add_servant_automation_total(owner_id, item, qty)
                    success = True
            elif duty == servants.DUTY_GATHER:
                result = self.start_gathering_patch(owner_id, player["name"])
                if result["ok"]:
                    collected = self._sum_node_quantities(result["nodes"])
                    boosted = {item: round(qty * (1 + bonus_pct)) for item, qty in collected.items()}
                    self.collect_gathering_patch(owner_id, boosted)
                    for item, qty in boosted.items():
                        self.db.add_servant_automation_total(owner_id, item, qty)
                    success = True
            else:  # farm -- harvest_all_farm already GRANTS at the base rate internally (single-
                   # phase, unlike mine/gather's roll-then-collect split), so the bonus tops up
                   # the difference afterward instead of being folded in beforehand.
                result = self.harvest_all_farm(owner_id, player["name"])
                success = result["plots_harvested"] > 0
                if success:
                    for item_name, qty in result["harvested"].items():
                        self.db.add_servant_automation_total(owner_id, item_name, qty)
                    if bonus_pct:
                        for item_name, qty in result["harvested"].items():
                            extra = round(qty * bonus_pct)
                            if extra:
                                self.db.add_item(owner_id, item_name, extra)
                                self.db.add_servant_automation_total(owner_id, item_name, extra)
            self.db.set_servant_next_tick(instance["instance_id"], now + servants.AUTOMATION_TICK_INTERVAL_SECONDS)
            completed.append({
                "user_id": owner_id, "name": player["name"], "servant_name": instance["name"],
                "duty": duty, "success": success, "yield_bonus_pct": bonus_pct,
            })
        return completed

    def get_servant_automation_totals(self, user_id: int) -> dict:
        """{item_name: lifetime quantity} gained via the servant Automation tick -- see /servant's
        Collected tab."""
        return self.db.get_servant_automation_totals(user_id)

    def _servant_yield_bonus(self, user_id: int, key: str) -> float:
        """Mirrors _grotto_yield_bonus's own shape -- mine/gather/farm have no generic bonus
        pool, so a Support-slotted servant flavored around gathering (servants.YIELD_BONUS_KEYS)
        needs this same direct read instead of riding compute_equipment_bonuses."""
        instance_id = self.db.get_equipped_servant_instance_ids(user_id).get(servants.SLOT_KEY_SUPPORT)
        if instance_id is None:
            return 0.0
        instance = self.db.get_servant_instance(instance_id)
        if instance is None:
            return 0.0
        servant = servants.SERVANT_CATALOG.get(instance["name"])
        if servant is None or servant.support_bonus_key != key:
            return 0.0
        affinity = servants.current_affinity_seconds(instance, int(time.time()))
        return servants.support_special_pct(servant, instance["star_level"], instance["level"], affinity)

    def combined_servant_power(self, user_id: int) -> Optional[float]:
        """Sum of both equipped servants' own Tier/Star/Level/Affinity investment (the exact
        TIER_STAT_BUDGET_PCT-based budget scaled_stat_bonuses computes per servant) -- None if
        either Combat or Support is empty. Used by dual_cultivate (see /view_servant) to scale
        its burst with how invested the equipped pair actually is, not just whether a pair
        exists at all."""
        equipped = self.get_equipped_servants(user_id)
        combat = equipped.get(servants.SLOT_KEY_COMBAT)
        support = equipped.get(servants.SLOT_KEY_SUPPORT)
        if combat is None or support is None:
            return None
        total = 0.0
        for instance in (combat, support):
            servant = servants.SERVANT_CATALOG.get(instance["name"])
            if servant is None:
                continue
            mult = (
                servants.STAR_STAT_MULTIPLIER[instance["star_level"]]
                * servants.LEVEL_STAT_MULTIPLIER.get(instance["level"], 1.0)
                * servants.affinity_multiplier(instance.get("current_affinity_seconds", 0))
            )
            total += servants.TIER_STAT_BUDGET_PCT[servant.tier] * mult
        return total

    # /view_servant's Dual Cultivate button -- requires a servant equipped in BOTH Combat and
    # Support. Mirrors /meditate's own "instant qi + essence, minutes-equivalent at the
    # player's real effective rate" mechanism exactly (see meditate()), just bigger and gated
    # behind owning a real Combat+Support pair, scaled further by combined_servant_power.
    DUAL_CULTIVATE_COOLDOWN_SECONDS = 6 * 3600
    DUAL_CULTIVATE_QI_MINUTES_BASE = 60
    DUAL_CULTIVATE_ESSENCE_PERCENT_BASE = 0.20

    def dual_cultivate(self, user_id: int, name: str) -> dict:
        """Returns {"ok": False, "reason": ...} (no servant pair equipped), {"ok": False,
        "remaining_seconds": ...} (on cooldown), or {"ok": True, "qi_gained", "qi",
        "essence_restored", "essence", "max_essence", "power_bonus_pct"}."""
        player = self.db.get_or_create_player(user_id, name)
        power = self.combined_servant_power(user_id)
        if power is None:
            return {"ok": False, "reason": "You need a servant equipped in BOTH Combat and Support to Dual Cultivate — see `/servant`'s Equip tab."}
        remaining = self._check_cooldown(player, "last_dual_cultivate_ts", self.DUAL_CULTIVATE_COOLDOWN_SECONDS)
        if remaining > 0:
            return {"ok": False, "remaining_seconds": remaining}
        effective_rate = self.db.get_qi_status(user_id)["effective_rate_per_minute"]
        qi_gained = effective_rate * self.DUAL_CULTIVATE_QI_MINUTES_BASE * (1 + power)
        new_qi = self.db.add_qi(user_id, qi_gained)
        essence_percent = self.DUAL_CULTIVATE_ESSENCE_PERCENT_BASE * (1 + power)
        essence_restored, essence, max_essence = self.db.restore_essence_percent(user_id, essence_percent)
        self.db.set_timestamp_column(user_id, "last_dual_cultivate_ts", int(time.time()))
        return {
            "ok": True, "qi_gained": qi_gained, "qi": new_qi,
            "essence_restored": essence_restored, "essence": essence, "max_essence": max_essence,
            "power_bonus_pct": power,
        }

    # Special stat_bonuses keys that aren't flat foundation stats — each fed straight
    # through to combat.resolve_attack (via hunt.py/raid.py), the qi-rate system, or
    # somewhere else specific (see canon_gu.py's docstring for where the newer ones go).
    SPECIAL_BONUS_KEYS = (
        "cultivation_speed_pct", "crit_chance_pct", "crit_damage_pct",
        "beast_damage_reduction_pct", "ignore_attack_chance", "lifesteal_percent", "low_hp_atk_bonus",
        "dodge_chance_pct", "stone_reward_bonus_pct", "loot_chance_bonus_pct", "essence_regen_pct",
        "clue_chance_bonus_pct",
        # Manual-only effects (see manual_view.EFFECT_LABELS) — no gear/accessory currently
        # rolls these, but they live in the same generic pool so that could change later.
        "breakthrough_success_pct", "essence_purity_pct", "technique_damage_pct",
        "physical_damage_pct", "insight_gain_pct", "cooldown_reduction_pct", "deviation_resistance_pct",
        # Alchemy success bonus (see craft_pill) — no gear/manual currently rolls this, only
        # the two Crimson Furnace Province accessories/artifact built for it, but it lives in
        # the same generic pool the same way every other special key does.
        "alchemy_success_pct",
        # World Boss (see world_boss.py) — consumed only in attack_world_boss. Beast Soul
        # Gu's "increased damage against beasts" reuses the EXISTING root-trait key
        # beast_damage_pct instead of a new one — see GameManager._trait_bonus's Gu
        # extension, which already makes any _trait_bonus-read key gear-grantable.
        "boss_damage_bonus_pct",
        # Nascent Soul Avatar (see avatar.py, Sword Soul/Demon Soul) — armor_penetration_pct
        # is consumed by combat.resolve_attack directly; execute_damage_pct is caller-side
        # (folded into damage_pct_bonus when the target is below 50% HP, mirroring the
        # existing beast_damage_pct caller-side pattern in raid.py). Both live in this same
        # generic pool so compute_equipment_bonuses' avatar-soul fold-in below needs no
        # separate special-casing for either.
        "armor_penetration_pct", "execute_damage_pct",
        # Nascent Soul Avatar gear (see game/avatar_gear.py's procedural tier system) —
        # total_damage_pct is caller-side, added unconditionally on top of whichever of
        # physical_damage_pct/technique_damage_pct already applies at every resolve_attack
        # call site (hunt/raid/battlefield_view/pvp_view/world-boss swing). soul_skill_
        # potency_pct/soul_projection_damage_pct are both consumed inside
        # soul_projection_multiplier, not resolve_attack directly. meditate_essence_bonus_pct
        # is read fresh in meditate() itself. death_qi_loss_reduction_pct existed already for
        # avatar SOULS (avatar.scaled_bonus) but wasn't in this generic pool -- now that it
        # is, the 3 death-penalty sites (hunt.py/raid.py/battlefield_view.py) read it through
        # this single generic `bonuses` dict instead of 3 separate manual sources, so gear
        # doesn't double up with what those manual reads already covered.
        "total_damage_pct", "soul_projection_damage_pct", "soul_skill_potency_pct",
        "meditate_essence_bonus_pct", "death_qi_loss_reduction_pct",
        # Spirit Severing Dao Paths (see game/dao_paths.py) — these 5 have no gear/manual/root
        # precedent anywhere else, only a Dao Path can grant them: fire_burn_damage_pct (Fire,
        # consumed in hunt.py/raid.py/tournament.py's burn-tick helper), meditate_cooldown_
        # reduction_pct (Wisdom, consumed only inside meditate()'s own _check_cooldown call —
        # deliberately separate from the generic cooldown_reduction_pct Time already uses, so
        # the two paths' bonuses stack instead of one overwriting the other), alchemy_bonus_
        # pill_chance_pct (Refinement, consumed in craft_pill), crafting_success_pct (Space,
        # consumed alongside professions.craft_success_chance), pill_save_chance_pct (Food,
        # consumed in use_item).
        "fire_burn_damage_pct", "meditate_cooldown_reduction_pct", "alchemy_bonus_pill_chance_pct",
        "crafting_success_pct", "pill_save_chance_pct",
        # White Heaven Gu (see game/content/canon_gu_white_heaven.py) -- Void Cloud Gu's
        # literal "dodge over the cap" ask. combat.resolve_attack already accepts a
        # max_dodge_chance override parameter; every player-defends call site (hunt.py's
        # _monster_turn, team_battle.py's _resolve_enemy_hit) adds this on top of the normal
        # combat.MAX_DODGE_CHANCE instead of leaving that cap hardcoded.
        "dodge_cap_bonus_pct",
        # Void Burial Gu / Nightmare Web Gu (see content/canon_gu_black_heaven.py) -- a
        # player-freezes-enemy chance, additive with any class-ability freeze_chance already
        # in play (e.g. Frostbinder's own Freeze action). The monster_frozen_rounds/frozen_
        # rounds mechanism itself already existed for that class ability; this key just makes
        # it Gu-grantable too (see hunt.py's _do_attack, team_battle.py's _resolve_round).
        "freeze_chance_pct",
        # Accessories/artifacts with a "clue_chance" effect_key promising faster travel/search
        # cooldowns (see accessories_data.py's own adaptation note: "No travel-time mechanic
        # exists -- 'faster travel' effects instead shave a little off /search's charge
        # recharge time") -- consumed in _effective_search_recharge_seconds, previously sat
        # unread in effect_params under several of these items (a live dead-effect bug fixed
        # 2026-08-13; see that method's own docstring).
        "search_recharge_reduction_pct",
        # Gu Pet (see game/gu_pet.py / /gu_pet) -- Vampiric Beetle's own Combat-Mode bleed DoT
        # (see hunt.py/team_battle.py/tournament.py's own tick blocks, reusing dao_paths.
        # fire_burn_tick_damage's exact engine). Deliberately distinct from monsters.py's own
        # bleed_damage_pct, which is a MONSTER ability against players, the opposite direction.
        "gu_pet_bleed_damage_pct",
        # Dao Realm Essences (see game/dao_essences.py / /dao_essence) — these 2 have no gear/
        # manual/root/Dao-Path precedent anywhere else, only a Dao Essence can grant them:
        # pvp_damage_pct (Essence of the Sovereign, consumed in pvp_view.py's/tournament.py's
        # own damage_pct_bonus expressions), gu_pet_power_pct (Essence of the Myriad Gu,
        # consumed directly inside this method's own Gu Pet Combat Mode block below since it
        # scales a value that's itself only computed here).
        "pvp_damage_pct", "gu_pet_power_pct",
    )

    # A manual's essence_recovery_pct (see manual_view.EFFECT_LABELS) is the exact same
    # mechanic as an accessory's essence_regen_pct (bonus % essence gained on item use — see
    # use_item) under a different display name, so it folds straight into that key instead of
    # needing its own separate SPECIAL_BONUS_KEYS slot and consumption site.
    _MANUAL_EFFECT_KEY_ALIASES = {"essence_recovery_pct": "essence_regen_pct"}

    def compute_equipment_bonuses(self, user_id: int) -> dict:
        """Sums equipped gear's stat_bonuses (plus the player's class's special_bonuses,
        e.g. Frostbinder's lifesteal — its hp_pct/def_pct-style bonuses are baked directly
        into foundation stats instead, see confirm_character/set_class, and active temporary
        combat buffs like Epic Physique's post-breakthrough vigor), split into flat
        foundation-stat bonuses and every special key (manual's cultivation bonus, Gu
        passives like crit/lifesteal/...). Despite the name this is really "everything that
        adds to combat stats right now" — combat views (hunt/raid/pvp) only ever read stats
        through here, so folding buffs in here means they don't need their own separate hook."""
        stats = {"str_stat": 0, "atk_stat": 0, "hp": 0, "spd_stat": 0, "def_stat": 0, "qi_stat": 0, "luck_stat": 0}
        special = {key: 0.0 for key in self.SPECIAL_BONUS_KEYS}
        player_row = self.db.get_player_row(user_id)
        player_rank = realms.STAGES[player_row["realm_index"]].great_realm_index + 1 if player_row else 1
        # Percentage-based crafted_gear bonuses (see blacksmith.py's roll_gear_stats) are
        # accumulated separately, additive-within-family across every equipped piece (same
        # convention chargen.py already uses for race/root/physique/path %s), and only
        # converted into an actual flat delta at the very end — against the player's own
        # gear-independent base stat (player_row), never a running total, so equip order
        # can't change the result and pieces can't compound off each other.
        crafted_pct_totals = {key: 0.0 for key in equipment.CRAFTED_GEAR_PCT_TO_FLAT}
        instance_gear_ids = self.db.get_equipped_gear_ids(user_id)
        accessory_ids = self.db.get_equipped_accessory_ids(user_id)
        gu_instance_ids = self.db.get_equipped_gu_instance_ids(user_id)
        servant_instance_ids = self.db.get_equipped_servant_instance_ids(user_id)
        for slot_key, item_name in self.db.get_equipped(user_id).items():
            if slot_key in instance_gear_ids:
                crafted = self.db.get_crafted_gear(instance_gear_ids[slot_key])
                stat_bonuses = crafted["stat_bonuses"] if crafted else {}
                power_mult = 1.0
            elif slot_key in accessory_ids:
                instance = self.db.get_accessory_instance(accessory_ids[slot_key])
                affix = self._affix_for_instance(instance)
                stat_bonuses = affix.stat_bonuses if affix else {}
                # Rank gate (section 2): equipped more than one rank above the player's own
                # cultivation rank still works, just at half numerical power.
                power_mult = 0.5 if (affix and affix.rank > player_rank + 1) else 1.0
            elif slot_key in gu_instance_ids:
                # Hairy-Man-blessed Gu instance (see game/grotto.py / gu_instances table) --
                # starts from the SAME base catalog stat_bonuses every unblessed copy of this
                # Gu has, then adds the instance's own accrued bonus_stat_bonuses on top.
                gu_instance = self.db.get_gu_instance(gu_instance_ids[slot_key])
                base_gear = equipment.EQUIPMENT.get(gu_instance["item_name"]) if gu_instance else None
                stat_bonuses = dict(base_gear.stat_bonuses) if base_gear else {}
                if gu_instance:
                    for key, value in gu_instance["bonus_stat_bonuses"].items():
                        stat_bonuses[key] = stat_bonuses.get(key, 0) + value
                power_mult = 1.0
            elif slot_key in servant_instance_ids:
                # Servant (see game/servants.py / /servant) -- Combat slot
                # is a pure stat stick at full scaled base_stats; Support slot trades half of
                # that for its own themed support_bonus_key at full value. A yield-flavored
                # support_bonus_key (servants.YIELD_BONUS_KEYS) is excluded here -- mine/gather/
                # farm don't read this pool at all, see GameManager._servant_yield_bonus.
                servant_instance = self.db.get_servant_instance(servant_instance_ids[slot_key])
                servant = servants.SERVANT_CATALOG.get(servant_instance["name"]) if servant_instance else None
                if servant and servant_instance:
                    affinity = servants.current_affinity_seconds(servant_instance, int(time.time()))
                    stat_bonuses = servants.scaled_stat_bonuses(servant, servant_instance["star_level"], servant_instance["level"], affinity)
                    if slot_key == servants.SLOT_KEY_SUPPORT:
                        stat_bonuses = {key: value * servants.SUPPORT_STAT_FRACTION for key, value in stat_bonuses.items()}
                        if servant.support_bonus_key not in servants.SUPPORT_KEYS_OUTSIDE_GENERIC_POOL:
                            pct = servants.support_special_pct(servant, servant_instance["star_level"], servant_instance["level"], affinity)
                            stat_bonuses[servant.support_bonus_key] = stat_bonuses.get(servant.support_bonus_key, 0) + pct
                else:
                    stat_bonuses = {}
                power_mult = 1.0
            else:
                gear = equipment.EQUIPMENT.get(item_name)
                stat_bonuses = gear.stat_bonuses if gear else {}
                power_mult = 1.0
            # Twin Gu Sovereign Physique's second Gu slot -- stays "equipped" (the item/row
            # is untouched) but its passive stat_bonuses only actually count while the player
            # CURRENTLY holds the qualifying physique, same "stays equipped, effect modulated
            # by current eligibility" precedent the accessory rank-gate above already uses.
            # Covers a player rerolling away from the physique after legitimately equipping a
            # second Gu, without needing to hook every physique-reroll entry point to force an
            # unequip -- the bonus just silently stops (and resumes if they reroll back in).
            if slot_key == equipment.GU_SLOT_KEY_2 and (not player_row or player_row["physique_name"] != equipment.TWIN_GU_SOVEREIGN_PHYSIQUE_NAME):
                stat_bonuses = {}
            for stat, value in stat_bonuses.items():
                if stat in crafted_pct_totals:
                    crafted_pct_totals[stat] += value * power_mult
                elif stat in special:
                    special[stat] += value * power_mult
                else:
                    stats[stat] = stats.get(stat, 0) + value * power_mult
        # Spirit Severing Dao Paths (see game/dao_paths.py / /dao_path) — a player can have
        # marks invested in several paths at once, so get_dao_path_totals already sums every
        # invested path's own linear-scaled bonus into one dict before this ever sees it.
        # str_pct/hp_pct/def_pct ride the exact same crafted_pct_totals resolution loop just
        # below that crafted gear's own % stats use (so they're inserted here, BEFORE that loop
        # runs); luck_flat is a flat luck_stat addition; every other key (including the 5
        # Dao-Path-only ones with no other precedent — see the SPECIAL_BONUS_KEYS comment above)
        # rides the generic special pool.
        if player_row:
            for stat, value in self.get_dao_path_totals(user_id).items():
                if stat == "luck_flat":
                    stats["luck_stat"] = stats.get("luck_stat", 0) + value
                elif stat in crafted_pct_totals:
                    crafted_pct_totals[stat] += value
                elif stat in special:
                    special[stat] += value
        # Dao Realm Essences (see game/dao_essences.py / /dao_essence) — up to 4 permanently
        # picked essences, each granting its full bonus (no scaling fraction, unlike Dao Paths
        # above). Same luck_flat/crafted_pct_totals/special triage; kept as a local so the Gu
        # Pet Combat Mode block further below can read gu_pet_power_pct off it directly.
        dao_essence_totals = self.get_dao_essence_totals(user_id) if player_row else {}
        for stat, value in dao_essence_totals.items():
            if stat == "luck_flat":
                stats["luck_stat"] = stats.get("luck_stat", 0) + value
            elif stat in crafted_pct_totals:
                crafted_pct_totals[stat] += value
            elif stat in special:
                special[stat] += value
        # Grotto (see game/grotto.py / /grotto) -- only alchemy_success_pct rides this generic
        # pool; cultivation_speed_pct is wired directly into database.py's _qi_rate_components
        # (the real qi-rate hook, NOT this pool -- see that function's own comment), and
        # grotto_crafting_success_pct/grotto_yield_pct are consumed directly at their own call
        # sites (get_crafting_success_bonus_total, _grotto_yield_bonus) since blacksmith craft
        # and mine/gather/farm yield don't read this pool at all.
        if player_row and player_row["grotto_level"]:
            special["alchemy_success_pct"] = special.get("alchemy_success_pct", 0) + grotto.grotto_bonuses(player_row["grotto_level"]).get("alchemy_success_pct", 0)
        # Servant collection bonus (see game/servants.py) -- a passive % just for owning
        # distinct servants beyond the 2 equipped slots, rewarding breadth even unequipped.
        # Rides the generic pool (no mine/gather/farm-style direct wiring needed) since both
        # keys it touches are already SPECIAL_BONUS_KEYS entries consumed elsewhere.
        if player_row:
            collection_pct = servants.collection_bonus_pct(self.db.count_distinct_servant_names(user_id))
            if collection_pct:
                special["stone_reward_bonus_pct"] = special.get("stone_reward_bonus_pct", 0) + collection_pct
                special["loot_chance_bonus_pct"] = special.get("loot_chance_bonus_pct", 0) + collection_pct
        if player_row:
            for pct_key, flat_key in equipment.CRAFTED_GEAR_PCT_TO_FLAT.items():
                pct = crafted_pct_totals[pct_key]
                if pct:
                    # hp_pct is a max-HP bonus, so it has to scale off the player's actual
                    # capacity (max_hp), never the fluctuating current "hp" column — using
                    # "hp" here would silently shrink the bonus while the player is hurt.
                    base = player_row["max_hp"] if flat_key == "hp" else player_row[flat_key]
                    stats[flat_key] = stats.get(flat_key, 0) + base * pct
        # Dao Companion (see game/dao_companion.py / /offer_companion) -- a slice of the
        # bonded partner's own raw stats, already flat (not a %, unlike the crafted_pct_totals
        # block above) since get_dao_companion_stat_bonus reads the partner's real base
        # columns directly, so it's added straight into stats like the combat-buff totals
        # below rather than routed through crafted_pct_totals.
        for stat, value in self.get_dao_companion_stat_bonus(user_id).items():
            stats[stat] = stats.get(stat, 0) + value
        character_class = chargen.get_character_class(self.db.get_character_class(user_id))
        if character_class:
            for stat, value in character_class.special_bonuses.items():
                if stat in special:
                    special[stat] += value
        for stat, value in self.db.get_active_combat_buff_totals(user_id).items():
            stats[stat] = stats.get(stat, 0) + value
        # Killer Move (see game/killer_move_gen.py) buffs -- a buff-kind Combat Killer Move's
        # lifesteal, or a loot-kind Support Killer Move's temporary loot_chance_bonus_pct --
        # ride the new generic buffs.special_bonuses JSON blob rather than the flat str/atk/
        # def/spd-only columns the loop just above reads.
        for stat, value in self.db.get_active_buff_special_bonuses(user_id).items():
            if stat in special:
                special[stat] += value
        # Overrides whatever the equipped-gear loop above picked up from just the OLD
        # catalog "manual" slot — get_qi_status's manual_bonus is the actual combined,
        # soft/hard-capped total across that slot AND the new primary/auxiliary assembled
        # manuals (see GameDatabase._qi_rate_components), the same number settle_qi actually
        # applies. Only equipment_view.py's display reads this key (nothing combat-related
        # does), so showing the real total here instead of just the old slot's slice is a
        # pure display fix, not a behavior change to anything else.
        qi_status = self.db.get_qi_status(user_id)
        special["cultivation_speed_pct"] = qi_status["manual_bonus"]
        # Every other manual page effect (breakthrough_success_pct, dodge_chance_pct,
        # technique/physical_damage_pct, insight_gain_pct, cooldown_reduction_pct,
        # deviation_resistance_pct, essence_recovery/purity_pct, hp_pct — see
        # manual_view.EFFECT_LABELS) — weighted primary 100%/auxiliary 100%, same as
        # cultivation, but NOT put through the cultivation-only soft/hard cap above.
        manual_effects = qi_status.get("manual_effect_bonuses", {})
        for key, value in manual_effects.items():
            key = self._MANUAL_EFFECT_KEY_ALIASES.get(key, key)
            if key in special:
                special[key] += value
        if player_row and manual_effects.get("hp_pct"):
            stats["hp"] = stats.get("hp", 0) + player_row["max_hp"] * manual_effects["hp_pct"]
        # A named root's AND a named physique's own SPECIAL_BONUS_KEYS-shaped bonuses
        # (alchemy_success_pct, clue_chance_bonus_pct, insight_gain_pct, essence_regen_pct —
        # see character_data.CharacterTraitSpec) ride the same combined pool every other
        # source here already does, so every existing consumer of this dict (craft_pill,
        # run_search, _grant_insight_dust, use_item, ...) picks up both automatically with no
        # separate hook of its own.
        if player_row:
            for spec in (chargen.get_root_spec(player_row["root_name"]), chargen.get_physique_spec(player_row["physique_name"])):
                if spec:
                    for stat, value in spec.stat_bonuses.items():
                        if stat in special:
                            special[stat] += value
        # Nascent Soul Avatar's own soul passive (see avatar.py) — same "ride the generic
        # pool" shape as the root/physique loop just above, level-scaled via
        # avatar.scaled_bonus. hp_pct isn't part of the generic pool (see the manual hp_pct
        # special case above), so it gets its own parallel one-liner the same way.
        # cultivation_speed_pct is ALSO excluded from this generic loop -- unlike every other
        # special key, it's already fully resolved via qi_status["manual_bonus"] above, which
        # (see GameDatabase._qi_rate_components) itself now sums the avatar soul's own
        # scaled_bonus for this key before the shared cultivation cap is applied; adding it
        # again here would double-count it in the displayed total.
        if player_row and player_row["avatar_soul"]:
            for stat in special:
                if stat == "cultivation_speed_pct":
                    continue
                bonus = avatar.scaled_bonus(player_row["avatar_soul"], player_row["avatar_level"], stat)
                if bonus:
                    special[stat] += bonus
            hp_bonus_pct = avatar.scaled_bonus(player_row["avatar_soul"], player_row["avatar_level"], "hp_pct")
            if hp_bonus_pct:
                stats["hp"] = stats.get("hp", 0) + player_row["max_hp"] * hp_bonus_pct
        # Nascent Soul Avatar's own rolled gear (see game/avatar_gear.py) — same "ride the
        # generic pool" shape as the avatar-soul block just above. hp_pct isn't part of the
        # generic pool (see the manual/avatar-soul hp_pct special cases above), so it gets
        # its own parallel one-liner here too, summed across every equipped instance.
        # cultivation_speed_pct is excluded the same way as the avatar-soul loop above, for
        # the same double-counting reason (_qi_rate_components already sums equipped avatar
        # gear's own cultivation_speed_pct into qi_status["manual_bonus"]).
        if player_row:
            for instance_id in self.db.get_avatar_equipped_instance_ids(user_id).values():
                instance = self.db.get_avatar_gear_instance(instance_id)
                if instance is None:
                    continue
                for stat, value in instance["stat_bonuses"].items():
                    if stat == "hp_pct":
                        stats["hp"] = stats.get("hp", 0) + player_row["max_hp"] * value
                    elif stat == "cultivation_speed_pct":
                        continue
                    elif stat in special:
                        special[stat] += value
        # Gu Pet (see game/gu_pet.py / /gu_pet) -- an active MATURE pet in Cultivation Mode
        # rides the exact same "generic pool" shape as the avatar-soul/avatar-gear blocks just
        # above, satiety-scaled (gu_pet.satiety_band). cultivation_speed_pct is excluded for
        # the SAME double-counting reason as those two blocks -- it's already folded into
        # qi_status["manual_bonus"] via GameDatabase._qi_rate_components instead (see that
        # function's own Gu Pet comment; this is the "_qi_rate_components is the real hook,
        # not compute_equipment_bonuses" trap this codebase has hit twice before with avatar
        # gear/soul, deliberately avoided here from the start). gear_budget_bonus_pct/manual_
        # rarity_bonus_pct (see gu_pet.roll_specialty_bonus) aren't in `special` either -- they
        # ride _gu_pet_cultivation_bonus at their own consumption sites (craft_gear/
        # assemble_manual) instead, same as every other _trait_bonus-only key.
        if player_row and player_row["active_gu_pet_id"]:
            pet = self.get_gu_pet(player_row["active_gu_pet_id"])
            if pet and pet["stage"] == gu_pet.STAGE_MATURE and pet["mode"] == gu_pet.MODE_CULTIVATION:
                satiety_mult, _ = gu_pet.satiety_band(pet["satiety"])
                for stat, value in pet["stat_bonuses"].items():
                    if stat == "cultivation_speed_pct":
                        continue
                    scaled = value * satiety_mult
                    if stat == "hp_pct":
                        stats["hp"] = stats.get("hp", 0) + player_row["max_hp"] * scaled
                    elif stat in special:
                        special[stat] += scaled
            # Combat Mode's own counterpart -- Vampiric Beetle/Flame-Spit Mantis's FIXED
            # per-species base values (see gu_pet.COMBAT_SPECIALTY_BASE_VALUES), scaled by
            # this pet's own rank combat_multiplier AND satiety, unlike the Cultivation block
            # above which reads real rolled/fed values straight off the pet's own
            # stat_bonuses. Read here every attack (hunt.py/team_battle.py call
            # compute_equipment_bonuses fresh per swing, not a stale encounter-start
            # snapshot), so armor_penetration_pct/crit_chance_pct/crit_damage_pct reach
            # combat.resolve_attack with zero new combat code -- gu_pet_bleed_damage_pct
            # additionally needs its own seed+tick engine (see hunt.py/team_battle.py/
            # tournament.py) since bleed isn't a resolve_attack kwarg the way crit/armor-pen
            # are. Crag-Shell Turtle has no entry in COMBAT_SPECIALTY_BASE_VALUES -- its own
            # shield rides apply_encounter_start_bonuses instead (see
            # _drain_active_gu_pet_combat_dispatch).
            elif pet and pet["stage"] == gu_pet.STAGE_MATURE and pet["mode"] == gu_pet.MODE_COMBAT:
                satiety_mult, _ = gu_pet.satiety_band(pet["satiety"])
                combat_mult = gu_pet.rank_scaling(pet["rank"])["combat_multiplier"]
                # Essence of the Myriad Gu's gu_pet_power_pct (see game/dao_essences.py) scales
                # this exact block multiplicatively -- the only place a pet's Combat Mode power
                # is computed, so it's the only place this key can be consumed.
                essence_power_mult = 1 + dao_essence_totals.get("gu_pet_power_pct", 0)
                for stat, base_value in gu_pet.COMBAT_SPECIALTY_BASE_VALUES.get(pet["species"], {}).items():
                    if stat in special:
                        special[stat] += base_value * combat_mult * satiety_mult * essence_power_mult
        return {"stats": stats, **special}

    # -- Spirit Severing Dao Paths (see game/dao_paths.py / /dao_path, /transmute) ------------
    # Spirit Severing is realms.GREAT_REALMS[SPIRIT_SEVERING_GREAT_REALM_INDEX] -- resolved by
    # name once here rather than hardcoding "4" at every gating check below, so every check
    # below keeps working even if GREAT_REALMS' ordering or length ever changes.

    SPIRIT_SEVERING_GREAT_REALM_INDEX = next(
        i for i, great_realm in enumerate(realms.GREAT_REALMS) if great_realm["name"] == "Spirit Severing"
    )

    def has_reached_spirit_severing(self, player_row: dict) -> bool:
        return realms.STAGES[player_row["realm_index"]].great_realm_index >= self.SPIRIT_SEVERING_GREAT_REALM_INDEX

    def get_dao_path_totals(self, user_id: int) -> dict:
        """Sums dao_paths.scaled_bonus(...) across every path the player has marks invested in
        (a player can invest in several at once — see dao_paths.py's own module docstring) into
        one combined dict, additive per key exactly like every other compute_equipment_bonuses
        source. Cheap enough to call on every compute_equipment_bonuses invocation — at most 14
        small dict merges, no extra DB round trip beyond the one JSON column read."""
        path_marks = self.db.get_dao_path_marks(user_id)
        totals: dict = {}
        for path_name, marks_invested in path_marks.items():
            for key, value in dao_paths.scaled_bonus(path_name, marks_invested).items():
                totals[key] = totals.get(key, 0.0) + value
        return totals

    def grant_dao_marks(self, user_id: int, player_row: Optional[dict] = None):
        """+1-3 Dao Marks (dao_paths.random_activity_marks) for a combat/exploration action —
        /hunt, /raid, /explore, /battlefield, /world_boss (attack), each tournament placement —
        gated to players who've reached Spirit Severing or beyond. Silently a no-op below that,
        matching the "optional, never blocks anything" framing this whole feature was built
        around: nothing before Spirit Severing ever needs to know this system exists."""
        if player_row is None:
            player_row = self.db.get_player_row(user_id)
        if not player_row or not self.has_reached_spirit_severing(player_row):
            return
        self.db.add_dao_marks(user_id, dao_paths.random_activity_marks())

    def backfill_dao_marks_for_all_players(self) -> list:
        """/backfill_dao_marks (admin, one-time) -- Spirit Severing/Dao Seeking/Ancient Realm's
        per-breakthrough Dao Marks lump sum (see dao_paths.breakthrough_marks) only ever fires
        going forward from attempt_breakthrough; a player who already crossed one or more of
        those substages before this existed (or before Dao Seeking/Ancient Realm were added to
        it) never got that grant. This walks every not-yet-backfilled confirmed player's
        history from realm_index 1 up to their CURRENT realm_index, rolling
        breakthrough_marks fresh for every qualifying stage they've already reached (same
        distribution they'd have gotten at the time, just rolled now), sums it into one grant,
        and marks them backfilled either way (even a 0-mark player, e.g. still below Spirit
        Severing, so this never re-scans them). Returns [{"user_id", "name", "marks_granted"},
        ...] for every player who actually received marks, for the caller to report."""
        granted = []
        for player in self.db.get_players_pending_dao_marks_backfill():
            total = 0
            for stage_index in range(1, player["realm_index"] + 1):
                stage = realms.STAGES[stage_index]
                marks = dao_paths.breakthrough_marks(stage.great_realm_name, stage.substage_name)
                if marks:
                    total += marks
            if total > 0:
                self.db.add_dao_marks(player["user_id"], total)
                granted.append({"user_id": player["user_id"], "name": player["name"], "marks_granted": total})
            self.db.mark_dao_marks_backfill_applied(player["user_id"])
        return granted

    def allocate_dao_marks(self, user_id: int, path_name: str, amount: int):
        """Moves `amount` Dao Marks from the banked pool into `path_name` — permanently; see
        GameDatabase.allocate_dao_marks, the only place this can fail (not enough banked, or it
        would push the path over dao_paths.DAO_MARKS_CAP_PER_PATH)."""
        if path_name not in dao_paths.DAO_PATHS:
            return False, f"**{path_name}** isn't a Dao Path."
        if amount <= 0:
            return False, "Enter a positive amount to allocate."
        if not self.db.allocate_dao_marks(user_id, path_name, amount):
            return False, "You don't have enough banked Dao Marks, or that would push the path over its 2,000 cap."
        return True, f"Allocated **{format_number(amount)}** Dao Marks into **{path_name}**."

    # -- Dao Realm Essences (see game/dao_essences.py / /dao_essence) -------------------------
    # Dao Realm is realms.GREAT_REALMS' current last entry -- resolved by name once here rather
    # than hardcoding its index, same reasoning as SPIRIT_SEVERING_GREAT_REALM_INDEX above.

    DAO_REALM_GREAT_REALM_INDEX = next(
        i for i, great_realm in enumerate(realms.GREAT_REALMS) if great_realm["name"] == "Dao Realm"
    )

    def has_reached_dao_realm(self, player_row: dict) -> bool:
        return realms.STAGES[player_row["realm_index"]].great_realm_index >= self.DAO_REALM_GREAT_REALM_INDEX

    def get_dao_essence_eligible_count(self, player_row: dict) -> int:
        """How many Dao Realm substage breakthroughs (Early/Middle/Late/Peak) this player has
        reached so far -- 0 until Dao Realm, up to dao_essences.DAO_ESSENCE_PICK_LIMIT (4) once
        Peak Dao Realm is reached. Name-keyed off realms.STAGES rather than a hardcoded
        realm_index range, mirroring dao_paths.breakthrough_marks' own name-keyed philosophy."""
        return sum(1 for s in realms.STAGES if s.great_realm_name == "Dao Realm" and s.index <= player_row["realm_index"])

    def get_dao_essence_totals(self, user_id: int) -> dict:
        """Sums each PICKED essence's full bonus dict (no scaling fraction, unlike Dao Path
        investment above — a pick is all-or-nothing) into one combined dict, additive per key
        exactly like every other compute_equipment_bonuses source."""
        picked = self.db.get_dao_essences_picked(user_id)
        totals: dict = {}
        for essence_name in picked:
            spec = dao_essences.DAO_ESSENCES.get(essence_name)
            if not spec:
                continue
            for key, value in spec.bonus.items():
                totals[key] = totals.get(key, 0.0) + value
        return totals

    def get_dao_essence_status(self, user_id: int, player_row: Optional[dict] = None) -> dict:
        """Read-only snapshot for /dao_essence's view and attempt_breakthrough's post-breakthrough
        check: how many picks the player has earned, how many they've spent, and which of the 9
        named essences are still available to choose from."""
        if player_row is None:
            player_row = self.db.get_player_row(user_id)
        picked = self.db.get_dao_essences_picked(user_id)
        eligible = self.get_dao_essence_eligible_count(player_row) if player_row else 0
        available_names = [name for name in dao_essences.DAO_ESSENCES if name not in picked]
        return {
            "picked": picked,
            "eligible": eligible,
            "pick_available": eligible > len(picked),
            "available_names": available_names,
        }

    def pick_dao_essence(self, user_id: int, essence_name: str):
        """Permanently locks in one of the 9 Dao Essences -- see GameDatabase.pick_dao_essence for
        the already-picked/over-cap guard; this method additionally gates on whether the player
        has actually earned a pick yet (breakthrough count), which the DB layer can't know."""
        if essence_name not in dao_essences.DAO_ESSENCES:
            return False, f"**{essence_name}** isn't a Dao Essence."
        status = self.get_dao_essence_status(user_id)
        if not status["pick_available"]:
            return False, "You have no Dao Essence pick available right now."
        if essence_name not in status["available_names"]:
            return False, f"You've already picked **{essence_name}**."
        if not self.db.pick_dao_essence(user_id, essence_name):
            return False, "That pick couldn't be completed."
        return True, f"You have permanently claimed **{essence_name}**."

    def get_transmute_status(self, user_id: int) -> dict:
        """Read-only -- for /transmute's view to show remaining charges without spending one."""
        marks_invested = self.db.get_dao_path_marks(user_id).get("Transformation", 0)
        max_charges = dao_paths.transmute_charges(marks_invested)
        used_today = self.db.get_transmute_uses_today(user_id)
        return {
            "marks_invested": marks_invested, "max_charges": max_charges,
            "used_today": used_today, "remaining": max(0, max_charges - used_today),
        }

    def transmute_item(self, user_id: int, name: str, source_item_name: str):
        """Transformation Dao Path's /transmute -- converts 1x source_item_name into 1x random
        item of the SAME tier from a DIFFERENT category (e.g. a Tier 7 Ore into a random Tier 7
        Pill), consuming one of today's charges (dao_paths.transmute_charges, scaling with
        marks invested — 0 marks invested means 0 charges, this path has to actually be
        invested in to use at all, not just picked)."""
        self.db.get_or_create_player(user_id, name)
        marks_invested = self.db.get_dao_path_marks(user_id).get("Transformation", 0)
        if marks_invested <= 0:
            return False, "You haven't invested any Dao Marks in the Transformation Dao Path yet — see `/dao_path`."
        source_item = ITEMS.get(source_item_name)
        source_tier = items.item_effective_tier(source_item) if source_item else None
        if source_item is None or source_tier is None:
            return False, "That item can't be transmuted."
        if self.db.get_inventory(user_id).get(source_item_name, 0) < 1:
            return False, f"You don't have a **{source_item_name}** to transmute."
        candidates = [
            it for it in ITEMS.values()
            if it.category != source_item.category and items.item_effective_tier(it) == source_tier
        ]
        if not candidates:
            return False, f"There's nothing else at Tier {source_tier} to transmute **{source_item_name}** into."
        max_charges = dao_paths.transmute_charges(marks_invested)
        if not self.db.try_use_transmute_charge(user_id, max_charges):
            return False, f"You've used all {max_charges} of today's transmute charges — come back tomorrow."
        target = random.choice(candidates)
        self.db.remove_item(user_id, source_item_name, 1)
        self.db.add_item(user_id, target.name, 1)
        return True, f"Transmuted **{source_item_name}** into **{target.name}**!"

    # -- Gu fusion: 2 copies of the same family+quality -> 1 copy of the next quality up --

    def gu_upgrade_candidates(self, user_id: int):
        """[(item_name, next_item_name, owned_quantity, duplicates_required), ...] for
        every tiered Gu the player owns enough copies of to fuse (see
        equipment.GU_UPGRADE_DUPLICATES_REQUIRED — the cost varies by current quality),
        strongest (by equipment.gear_power_score) first — a big collection can easily blow
        past the 25-option Select cap this feeds, so the best candidates should be the ones
        that survive the cut, not an arbitrary slice."""
        inventory = self.db.get_inventory(user_id)
        candidates = []
        for item_name, qty in inventory.items():
            family, quality = equipment.parse_gu_name(item_name)
            if family is None:
                continue
            required = equipment.GU_UPGRADE_DUPLICATES_REQUIRED.get(quality)
            if required is None or qty < required:
                continue
            next_quality = equipment.GU_NEXT_QUALITY.get(quality)
            if next_quality is None:
                continue
            next_name = equipment.gu_item_name(family, next_quality)
            if next_name not in equipment.EQUIPMENT:
                continue
            candidates.append((item_name, next_name, qty, required))
        candidates.sort(key=lambda c: -equipment.gear_power_score(equipment.EQUIPMENT[c[0]]))
        return candidates

    def upgrade_gu(self, user_id: int, name: str, item_name: str):
        self.db.get_or_create_player(user_id, name)
        family, quality = equipment.parse_gu_name(item_name)
        if family is None:
            return False, "That isn't a tiered Gu.", None
        next_quality = equipment.GU_NEXT_QUALITY.get(quality)
        if next_quality is None:
            return False, f"**{item_name}** is already at the maximum quality.", None
        next_name = equipment.gu_item_name(family, next_quality)
        if next_name not in equipment.EQUIPMENT:
            return False, f"The {next_quality} tier of {family} doesn't exist yet.", None
        required = equipment.GU_UPGRADE_DUPLICATES_REQUIRED[quality]
        if not self.db.remove_item(user_id, item_name, required):
            return False, f"You need {required} copies of **{item_name}** to fuse it (you have {self.db.get_inventory(user_id).get(item_name, 0)}).", None
        self.db.add_item(user_id, next_name, 1)
        return True, f"Fused {required}x **{item_name}** into 1x **{next_name}**!", next_name

    def gu_breakdown_candidates(self, user_id: int):
        """[(item_name, owned_quantity, stones_each), ...] for every Gu the player currently
        owns (unequipped copies only — see equip_item), strongest first, same as
        gu_upgrade_candidates above."""
        inventory = self.db.get_inventory(user_id)
        candidates = []
        for item_name, qty in inventory.items():
            gear = equipment.EQUIPMENT.get(item_name)
            if gear is None or gear.slot_type != "Gu":
                continue
            candidates.append((item_name, qty, equipment.gu_breakdown_value(item_name)))
        candidates.sort(key=lambda c: -equipment.gear_power_score(equipment.EQUIPMENT[c[0]]))
        return candidates

    def breakdown_gu(self, user_id: int, name: str, item_name: str, quantity: int = 1):
        """Consumes up to `quantity` copies of item_name (a Gu) for spirit stones, clamped to
        how many are actually owned. Returns (ok, message, stones_gained)."""
        self.db.get_or_create_player(user_id, name)
        gear = equipment.EQUIPMENT.get(item_name)
        if gear is None or gear.slot_type != "Gu":
            return False, "That isn't a Gu.", 0
        owned = self.db.get_inventory(user_id).get(item_name, 0)
        quantity = min(quantity, owned)
        if quantity <= 0:
            return False, f"You don't own a **{item_name}** to break down.", 0
        self.db.remove_item(user_id, item_name, quantity)
        stones = equipment.gu_breakdown_value(item_name) * quantity
        self.db.add_spirit_stones(user_id, stones)
        return True, f"Broke down {quantity}x **{item_name}** for **{format_number(stones)}** 🪙 spirit stones.", stones

    # -- Gu Pet: the Gu Refiner profession's own crafting action (see game/gu_pet.py /
    # /gu_pet) -- sacrifice 1-3 Immortal-quality Gu (pure "energy mass," never carrying its
    # own stats/identity over -- see gu_pet.REFINE_REQUIRED_GU_QUALITY's own comment) plus
    # Soul Nourishing Pill/Soul Crystal catalysts into a blank Rank I-VII Gu Pet. -----------

    def gu_pet_refine_candidates(self, user_id: int):
        """[(item_name, owned_quantity), ...] for every Immortal-quality Gu the player owns at
        least gu_pet.REFINE_MIN_SACRIFICE copies of, strongest first -- same shape/reasoning as
        gu_upgrade_candidates (a big collection can blow past Discord's 25-option Select cap,
        so the strongest candidates should be the ones that survive the cut)."""
        inventory = self.db.get_inventory(user_id)
        candidates = []
        for item_name, qty in inventory.items():
            family, quality = equipment.parse_gu_name(item_name)
            if family is None or quality != gu_pet.REFINE_REQUIRED_GU_QUALITY or qty < gu_pet.REFINE_MIN_SACRIFICE:
                continue
            candidates.append((item_name, qty))
        candidates.sort(key=lambda c: -equipment.gear_power_score(equipment.EQUIPMENT[c[0]]))
        return candidates

    def gu_pet_refine_race_bonus_pct(self, player: dict, key: str) -> float:
        """Hairy Man's own 'unrivaled refiners of the Gu world' bonus (gu_refiner_success_pct/
        gu_refiner_failure_refund_pct, see character_data.py) -- the only race with a Gu-
        refinement-flavored bonus today, 0 for every other race. Kept as its own small race-
        only lookup rather than folded into _trait_bonus (root/physique/Gu only, deliberately
        never reads race -- see its own docstring), so this stays scoped to exactly the one
        place it applies instead of silently changing every other _trait_bonus call site too."""
        race = chargen.get_race(player["race"])
        return race.stat_bonuses.get(key, 0) if race else 0

    def refine_gu_pet(self, user_id: int, name: str, item_name: str, quantity: int, rng: Optional[random.Random] = None) -> dict:
        """Returns {"ok": False, "reason": ...} on a validation refusal (never spends
        anything), or {"ok": True, "outcome": "critical"|"standard"|"minor_failure"|
        "major_failure", "message": ..., "target_rank": ..., **outcome-specific fields} once
        the ritual actually runs. Materials are ALWAYS consumed once validation passes (Minor
        Failure refunds the sacrificed Gu specifically -- see below), matching craft_gear/
        craft_pill's own "consume regardless of outcome" risk model.

        The Gu Pet's own rank is no longer player-chosen (see gu_pet.roll_target_rank) -- it's
        rolled internally, weighted toward whatever rank the player's own Gu Refiner rank
        already natively qualifies for (gu_pet.natively_qualified_rank), by explicit request
        ("cant choose what type of pet you are going for, instead get a random one based on
        your gu refining level"). Catalyst costs are priced off that SAME natively-qualified
        rank (known upfront, unlike the roll) so the player always knows the cost before
        committing, even though the actual rolled rank -- and therefore the real success
        chance for THIS specific attempt -- isn't revealed until after."""
        player = self.db.get_or_create_player(user_id, name)
        if not (gu_pet.REFINE_MIN_SACRIFICE <= quantity <= gu_pet.REFINE_MAX_SACRIFICE):
            return {"ok": False, "reason": f"You must sacrifice between {gu_pet.REFINE_MIN_SACRIFICE} and {gu_pet.REFINE_MAX_SACRIFICE} {gu_pet.REFINE_REQUIRED_GU_QUALITY} Gu."}
        family, quality = equipment.parse_gu_name(item_name)
        if family is None:
            return {"ok": False, "reason": "That isn't a tiered Gu."}
        if quality != gu_pet.REFINE_REQUIRED_GU_QUALITY:
            return {"ok": False, "reason": f"Only **{gu_pet.REFINE_REQUIRED_GU_QUALITY}**-quality Gu can be sacrificed (that one was {quality})."}
        inventory = self.db.get_inventory(user_id)
        if inventory.get(item_name, 0) < quantity:
            return {"ok": False, "reason": f"You only own {inventory.get(item_name, 0)}x **{item_name}** (need {quantity})."}
        catalyst_rank = gu_pet.natively_qualified_rank(player["gu_refiner_rank"])
        catalysts = gu_pet.refine_catalyst_recipe(catalyst_rank)
        missing = {mat: qty for mat, qty in catalysts.items() if inventory.get(mat, 0) < qty}
        if missing:
            missing_text = ", ".join(f"{qty}x {mat} (have {inventory.get(mat, 0)})" for mat, qty in missing.items())
            return {"ok": False, "reason": f"Missing catalysts: {missing_text}."}

        rng = rng or random.Random()
        target_rank = gu_pet.roll_target_rank(player["gu_refiner_rank"], rng)
        race_success_bonus = self.gu_pet_refine_race_bonus_pct(player, "gu_refiner_success_pct")
        race_refund_pct = self.gu_pet_refine_race_bonus_pct(player, "gu_refiner_failure_refund_pct")
        chance = gu_pet.refine_success_chance(player["gu_refiner_rank"], target_rank, quantity, race_success_bonus)
        success = rng.random() < chance

        self.db.remove_item(user_id, item_name, quantity)
        for mat, qty in catalysts.items():
            self.db.remove_item(user_id, mat, qty)

        if success:
            is_critical = rng.random() < gu_pet.REFINE_CRITICAL_SHARE_OF_SUCCESS
            days_required = gu_pet.growth_days_required(rng)
            if is_critical:
                days_required = max(gu_pet.GROWTH_DAYS_MIN, days_required - gu_pet.CRITICAL_SUCCESS_GROWTH_DAYS_REDUCTION)
            pet_id = self.db.create_gu_pet(user_id, target_rank, days_required)
            outcome = "critical" if is_critical else "standard"
            flavor = "The ritual flares with unexpected power" if is_critical else "The ritual completes"
            message = (
                f"✨ {flavor} — the ritual settles on a blank **Rank {target_rank} ({gu_pet.rank_to_rarity(target_rank)})** Gu Pet, which stirs to life! "
                f"Feed it through `/gu_pet` (once/day) to help it grow (needs {days_required} days' worth of feeding — "
                "feed more material per visit to cover several days at once)."
            )
            return {"ok": True, "outcome": outcome, "message": message, "pet_id": pet_id, "chance": chance, "target_rank": target_rank}

        def _refund_materials(gu_qty: int, catalyst_qtys: dict) -> str:
            """Hairy Man's own gu_refiner_failure_refund_pct passive -- 'Failed Gu refinements
            refund 50% of the materials,' applied uniformly to whatever this failure actually
            destroyed. Ceiling-rounded so even a single lost unit gives back something real
            (plain round() would bankers'-round 1 * 0.5 down to 0, silently doing nothing)."""
            if race_refund_pct <= 0:
                return ""
            parts = []
            if gu_qty > 0:
                refunded_gu = math.ceil(gu_qty * race_refund_pct)
                self.db.add_item(user_id, item_name, refunded_gu)
                parts.append(f"{refunded_gu}x {item_name}")
            for mat, qty in catalyst_qtys.items():
                refunded_qty = math.ceil(qty * race_refund_pct)
                if refunded_qty > 0:
                    self.db.add_item(user_id, mat, refunded_qty)
                    parts.append(f"{refunded_qty}x {mat}")
            return f" Your race's refining mastery salvages back {', '.join(parts)}." if parts else ""

        is_major = rng.random() < gu_pet.REFINE_MAJOR_FAILURE_SHARE_OF_FAILURE
        if is_major:
            self.db.add_buff(
                user_id, "Aperture Backlash", gu_pet.APERTURE_BACKLASH_QI_MULTIPLIER_PENALTY,
                gu_pet.APERTURE_BACKLASH_DURATION_SECONDS,
            )
            self.db.add_item(user_id, gu_pet.MUTATED_GU_RESIDUE_ITEM_NAME, 1)
            refund_note = _refund_materials(quantity, catalysts)
            message = (
                f"💥 The ritual reaches for a Rank {target_rank} Gu Pet and backfires violently — {quantity}x **{item_name}** "
                f"and every catalyst are destroyed, and your dantian suffers **Aperture Backlash** (reduced Qi regen for "
                f"{gu_pet.APERTURE_BACKLASH_DURATION_SECONDS // 60} minutes). A twisted **{gu_pet.MUTATED_GU_RESIDUE_ITEM_NAME}** is all that's left.{refund_note}"
            )
            return {"ok": True, "outcome": "major_failure", "message": message, "chance": chance, "target_rank": target_rank}

        self.db.add_item(user_id, item_name, quantity)
        # The sacrificed Gu is already fully refunded for everyone -- Hairy Man's passive only
        # has real catalysts left to salvage back here.
        refund_note = _refund_materials(0, catalysts)
        message = (
            f"💨 The ritual reaches for a Rank {target_rank} Gu Pet and fizzles — the catalysts are consumed, "
            f"but your {quantity}x **{item_name}** are unharmed and refunded.{refund_note}"
        )
        return {"ok": True, "outcome": "minor_failure", "message": message, "chance": chance, "target_rank": target_rank}

    def get_player_gu_pets(self, user_id: int) -> list:
        return [self._settle_gu_pet_satiety(pet) for pet in self.db.get_player_gu_pets(user_id)]

    def get_gu_pet(self, pet_id: int) -> Optional[dict]:
        return self._settle_gu_pet_satiety(self.db.get_gu_pet(pet_id))

    def set_active_gu_pet(self, user_id: int, pet_id: Optional[int]):
        self.db.set_active_gu_pet(user_id, pet_id)

    def feed_gu_pet(self, user_id: int, name: str, pet_id: int, item_name: str, quantity: int = 1) -> dict:
        """One feed ACTION per real day (see gu_pet.FEED_COOLDOWN_SECONDS) while
        stage='growth' -- refused entirely once mature (see the Status tab's satiety upkeep
        instead) or once already fed enough days to crystallize (see GameManager.
        crystallize_gu_pet, which is what actually consumes this milestone). quantity fed
        advances growth_days_fed by that same amount (not a flat +1) -- feeding more in one
        sitting shortens the total real-time span, still gated to once/day so it can't be
        finished in a single instant; the ratio-shaping choice of WHICH category to feed stays
        entirely up to the player either way. Auto-clamped to never consume more than the pet
        still needs, so a big stockpile never gets wasted past the finish line. Returns
        {"ok": False, "reason": ...} or {"ok": True, "message", "days_fed", "days_required",
        "ready_to_crystallize"}."""
        self.db.get_or_create_player(user_id, name)
        pet = self.db.get_gu_pet(pet_id)
        if pet is None or pet["owner_id"] != user_id:
            return {"ok": False, "reason": "You don't own that Gu Pet."}
        if pet["stage"] != gu_pet.STAGE_GROWTH:
            return {"ok": False, "reason": "This Gu Pet has already matured — see the Status tab for its satiety upkeep instead."}
        if pet["growth_days_fed"] >= pet["growth_days_required"]:
            return {"ok": False, "reason": "This Gu Pet has been fed enough to crystallize — use the Status tab to complete it."}
        now = int(time.time())
        if now - pet["last_fed_ts"] < gu_pet.FEED_COOLDOWN_SECONDS:
            from .ui_utils import format_duration
            remaining = gu_pet.FEED_COOLDOWN_SECONDS - (now - pet["last_fed_ts"])
            return {"ok": False, "reason": f"This Gu Pet has already been fed today — try again in {format_duration(remaining)}."}
        category_tier = gu_pet.feed_category_and_tier(item_name)
        if category_tier is None:
            return {"ok": False, "reason": "That can't be fed to a growing Gu Pet — try an Ore, Herb, Beast Material, Beast Core, or Pill."}
        if quantity < 1:
            return {"ok": False, "reason": "Quantity must be at least 1."}
        quantity = min(quantity, pet["growth_days_required"] - pet["growth_days_fed"])
        owned = self.db.get_inventory(user_id).get(item_name, 0)
        if owned < quantity:
            return {"ok": False, "reason": f"You only own {owned}x **{item_name}** (need {quantity})."}

        category, tier = category_tier
        # Consecutive REAL days, not just "fed at all" -- a gap of 2+ days since the last
        # feed resets the streak, same "did you actually keep the daily habit" idiom every
        # other streak-flavored mechanic in this codebase already uses.
        was_yesterday = pet["last_fed_ts"] > 0 and (now - pet["last_fed_ts"]) < 2 * gu_pet.FEED_COOLDOWN_SECONDS
        new_streak = pet["feed_streak_days"] + 1 if was_yesterday else 1

        self.db.remove_item(user_id, item_name, quantity)
        primary_key, secondary_key = gu_pet.CATEGORY_STAT_KEYS[category]
        streak_mult = 1 + gu_pet.streak_bonus_pct(new_streak)
        yield_mult = gu_pet.QI_MULTIPLIER_PILL_FEED_YIELD_MULTIPLIER if item_name.startswith("Qi Multiplier Pill") else 1.0
        primary_delta = gu_pet.BASE_YIELD_PER_TIER * tier * quantity * streak_mult * yield_mult

        stat_bonuses = dict(pet["stat_bonuses"])
        stat_bonuses[primary_key] = stat_bonuses.get(primary_key, 0) + primary_delta
        if secondary_key:
            stat_bonuses[secondary_key] = stat_bonuses.get(secondary_key, 0) + primary_delta * gu_pet.SECONDARY_YIELD_FRACTION

        fed_totals = dict(pet["fed_totals"])
        fed_totals[category] = fed_totals.get(category, 0) + quantity

        new_days_fed = min(pet["growth_days_required"], pet["growth_days_fed"] + quantity)
        self.db.update_gu_pet(
            pet_id, stat_bonuses=stat_bonuses, fed_totals=fed_totals,
            growth_days_fed=new_days_fed, feed_streak_days=new_streak, last_fed_ts=now,
        )
        ready = new_days_fed >= pet["growth_days_required"]
        message = (
            f"🍖 Fed {quantity}x **{item_name}** ({category.replace('_', ' ').title()}, Tier {tier}) — "
            f"day {new_days_fed}/{pet['growth_days_required']}, streak {new_streak}."
            + (" This Gu Pet is ready to crystallize!" if ready else "")
        )
        return {"ok": True, "message": message, "days_fed": new_days_fed, "days_required": pet["growth_days_required"], "ready_to_crystallize": ready}

    def gu_pet_feedable_inventory(self, user_id: int) -> list:
        """[(item_name, owned_quantity, category, tier), ...] for every owned item
        gu_pet.feed_category_and_tier recognizes, tier-descending (a player's best material
        should surface first, same "strongest first" convention gu_upgrade_candidates/
        gu_pet_refine_candidates already use)."""
        candidates = []
        for item_name, qty in self.db.get_inventory(user_id).items():
            category_tier = gu_pet.feed_category_and_tier(item_name)
            if category_tier is None:
                continue
            category, tier = category_tier
            candidates.append((item_name, qty, category, tier))
        candidates.sort(key=lambda c: -c[3])
        return candidates

    def feed_gu_pet_satiety(self, user_id: int, name: str, pet_id: int, item_name: str, quantity: int = 1) -> dict:
        """Upkeep feeding for a MATURE pet (see gu_pet.SATIETY_REFILL_PER_ITEM) -- any of the
        5 feed categories, but the item's tier must exactly match this pet's own locked rank
        (gu_pet.rank_scaling(rank)["satiety_material_tier"]), no daily gate."""
        self.db.get_or_create_player(user_id, name)
        pet = self.db.get_gu_pet(pet_id)
        if pet is None or pet["owner_id"] != user_id:
            return {"ok": False, "reason": "You don't own that Gu Pet."}
        if pet["stage"] != gu_pet.STAGE_MATURE:
            return {"ok": False, "reason": "This Gu Pet hasn't crystallized yet — use the Feed tab's growth feeding instead."}
        pet = self._settle_gu_pet_satiety(pet)
        category_tier = gu_pet.feed_category_and_tier(item_name)
        if category_tier is None:
            return {"ok": False, "reason": "That can't be fed to a Gu Pet — try an Ore, Herb, Beast Material, Beast Core, or Pill."}
        category, tier = category_tier
        required_tier = gu_pet.rank_scaling(pet["rank"])["satiety_material_tier"]
        if tier != required_tier:
            return {"ok": False, "reason": f"This Rank {pet['rank']} Gu Pet needs Tier {required_tier} materials for its upkeep (that was Tier {tier})."}
        if quantity < 1:
            return {"ok": False, "reason": "Quantity must be at least 1."}
        owned = self.db.get_inventory(user_id).get(item_name, 0)
        if owned < quantity:
            return {"ok": False, "reason": f"You only own {owned}x **{item_name}** (need {quantity})."}
        if pet["satiety"] >= gu_pet.SATIETY_MAX:
            return {"ok": False, "reason": "This Gu Pet is already fully satiated."}

        self.db.remove_item(user_id, item_name, quantity)
        new_satiety = min(gu_pet.SATIETY_MAX, pet["satiety"] + gu_pet.SATIETY_REFILL_PER_ITEM * quantity)
        self.db.update_gu_pet(pet_id, satiety=new_satiety)
        _, band_label = gu_pet.satiety_band(new_satiety)
        message = f"🍖 Fed {quantity}x **{item_name}** — Satiety now **{new_satiety:.0f}/100** ({band_label})."
        return {"ok": True, "message": message, "satiety": new_satiety}

    def crystallize_gu_pet(self, user_id: int, name: str, pet_id: int) -> dict:
        """Locks in a permanent species + Path from the RATIO of everything fed during
        growth (see gu_pet.crystallize) once the growth window is actually complete --
        growth stops forever the moment this succeeds (feed_gu_pet already refuses once
        stage != 'growth'). Mode defaults to match the newly-locked Path (a Combat-Path pet
        starts in Combat Mode, Cultivation-Path in Cultivation Mode) -- the player can still
        toggle it later (see toggle_gu_pet_mode, a later phase)."""
        self.db.get_or_create_player(user_id, name)
        pet = self.db.get_gu_pet(pet_id)
        if pet is None or pet["owner_id"] != user_id:
            return {"ok": False, "reason": "You don't own that Gu Pet."}
        if pet["stage"] != gu_pet.STAGE_GROWTH:
            return {"ok": False, "reason": "This Gu Pet has already crystallized."}
        if pet["growth_days_fed"] < pet["growth_days_required"]:
            remaining = pet["growth_days_required"] - pet["growth_days_fed"]
            return {"ok": False, "reason": f"This Gu Pet still needs {remaining} more day(s) of feeding before it can crystallize."}

        species_key, path = gu_pet.crystallize(pet["fed_totals"])
        mode = gu_pet.MODE_COMBAT if path == gu_pet.PATH_COMBAT else gu_pet.MODE_CULTIVATION
        stat_bonuses = dict(pet["stat_bonuses"])
        stat_bonuses.update(gu_pet.roll_specialty_bonus(species_key, pet["rank"]))
        # Generated from pet_flavor_seed -- the SAME seed gu_pet_images.build_pet_prompt uses
        # for this pet's own portrait, so the name and the image stay thematically coherent
        # (see gu_pet.pet_flavor_seed's own docstring) rather than two independently-random
        # systems producing an unrelated name and an unrelated look.
        pet_name = gu_pet.generate_pet_name(random.Random(gu_pet.pet_flavor_seed(pet)))
        self.db.update_gu_pet(
            pet_id, stage=gu_pet.STAGE_MATURE, species=species_key, path=path, mode=mode, name=pet_name,
            stat_bonuses=stat_bonuses, satiety=gu_pet.SATIETY_MAX, last_satiety_update_ts=int(time.time()),
        )
        species = gu_pet.SPECIES[species_key]
        message = f"✨ {species.emoji} **{pet_name}** crystallizes into a **{species.name}** ({path})! {species.role_text}"
        return {"ok": True, "message": message, "species": species_key, "path": path, "name": pet_name}

    async def get_or_create_gu_pet_image(self, pet_id: int) -> Optional[str]:
        """The only async method on GameManager -- see game/gu_pet_images.py's own module
        docstring for why generate_pet_image needs a genuine await rather than asyncio.
        to_thread. The DB reads/writes in here still go through asyncio.to_thread (blocking
        sqlite calls, same as every other DB access in this codebase) -- only the actual
        network call is awaited directly. Checks the shared cache (Common/Uncommon/Rare) or
        the pet's own image_path (Epic+) first; on a miss, generates, writes the PNG to
        config.IMAGE_CACHE_DIR, and records the path. Returns None (never raises) on any
        failure along the way -- a missing portrait must never block anything about owning or
        using a Gu Pet."""
        pet = await asyncio.to_thread(self.db.get_gu_pet, pet_id)
        if pet is None or pet["species"] is None:
            return None
        unique = gu_pet_images.should_generate_unique_image(pet)
        if unique:
            if pet["image_path"] and os.path.exists(pet["image_path"]):
                return pet["image_path"]
        else:
            cache_key = gu_pet_images.get_pet_cache_key(pet)
            cached_path = await asyncio.to_thread(self.db.get_cached_gu_pet_image, cache_key)
            if cached_path and os.path.exists(cached_path):
                return cached_path

        image_bytes = await gu_pet_images.generate_pet_image(pet)
        if image_bytes is None:
            return None

        safe_key = gu_pet_images.get_pet_cache_key(pet).replace("|", "_").replace(" ", "-")
        filename = f"gu_pet_{pet_id}.png" if unique else f"gu_pet_shared_{safe_key}.png"
        path = os.path.join(IMAGE_CACHE_DIR, filename)
        try:
            with open(path, "wb") as f:
                f.write(image_bytes)
        except OSError:
            return None

        if unique:
            await asyncio.to_thread(self.db.update_gu_pet, pet_id, image_path=path)
        else:
            await asyncio.to_thread(self.db.set_cached_gu_pet_image, cache_key, path)
        return path

    def _settle_gu_pet_satiety(self, pet: Optional[dict]) -> Optional[dict]:
        """Lazy time-based settlement, mirroring GameDatabase.settle_qi's own idiom (no
        background tick loop -- every read just settles up to "now" first). Cultivation Mode
        drains satiety by real elapsed hours; Combat Mode's own drain is flat-per-dispatch
        instead (see apply_encounter_start_bonuses), so a Combat-Mode pet's elapsed real time
        advances the anchor timestamp here WITHOUT draining anything -- otherwise switching a
        long-idle Combat-Mode pet into Cultivation Mode would retroactively charge it for
        every hour it sat in Combat Mode. No-op for a still-growing pet (satiety only matters
        once stage='mature') or a pet that was already settled this same second."""
        if pet is None or pet["stage"] != gu_pet.STAGE_MATURE:
            return pet
        now = int(time.time())
        last = pet["last_satiety_update_ts"] or now
        if now <= last:
            return pet
        if pet["mode"] == gu_pet.MODE_CULTIVATION:
            elapsed_hours = (now - last) / 3600.0
            new_satiety = max(0.0, pet["satiety"] - elapsed_hours * gu_pet.SATIETY_DRAIN_PER_CULTIVATION_HOUR)
        else:
            new_satiety = pet["satiety"]
        self.db.update_gu_pet(pet["pet_id"], satiety=new_satiety, last_satiety_update_ts=now)
        pet = dict(pet)
        pet["satiety"] = new_satiety
        pet["last_satiety_update_ts"] = now
        return pet

    def toggle_gu_pet_mode(self, user_id: int, name: str, pet_id: int, pay_fee: bool = False) -> dict:
        """Flips a mature Gu Pet between Combat and Cultivation Mode. Gated by a flat 10-
        minute cooldown (gu_pet.MODE_SWITCH_COOLDOWN_SECONDS) shared across ALL of a player's
        pets (players.last_gu_pet_mode_switch_ts, not a per-pet column -- mirrors how the
        pet's own active slot is a single players.active_gu_pet_id pointer), unless pay_fee
        bypasses it for a flat gu_pet.MODE_SWITCH_FEE_SPIRIT_STONES cost. Returns {"ok":
        False, "reason": ..., "on_cooldown": True, "remaining": ...} while on cooldown and
        pay_fee wasn't set (the view's own Mode tab offers a "pay to switch now" button in
        that case), or {"ok": True, "message": ..., "mode": ...} once it actually switches."""
        player = self.db.get_or_create_player(user_id, name)
        pet = self.db.get_gu_pet(pet_id)
        if pet is None or pet["owner_id"] != user_id:
            return {"ok": False, "reason": "You don't own that Gu Pet."}
        if pet["stage"] != gu_pet.STAGE_MATURE:
            return {"ok": False, "reason": "This Gu Pet hasn't crystallized yet — it has no Mode to switch."}

        now = int(time.time())
        last_switch = player["last_gu_pet_mode_switch_ts"] or 0
        remaining = gu_pet.MODE_SWITCH_COOLDOWN_SECONDS - (now - last_switch)
        if remaining > 0:
            if not pay_fee:
                from .ui_utils import format_duration
                return {
                    "ok": False,
                    "reason": f"Mode can be switched again in {format_duration(remaining)}, or pay **{format_number(gu_pet.MODE_SWITCH_FEE_SPIRIT_STONES)}** spirit stones to switch now.",
                    "on_cooldown": True, "remaining": remaining,
                }
            if not self.db.spend_spirit_stones(user_id, gu_pet.MODE_SWITCH_FEE_SPIRIT_STONES):
                return {"ok": False, "reason": f"Switching early costs **{format_number(gu_pet.MODE_SWITCH_FEE_SPIRIT_STONES)}** spirit stones (you have {format_number(player['spirit_stones'])})."}

        pet = self._settle_gu_pet_satiety(pet)
        new_mode = gu_pet.MODE_CULTIVATION if pet["mode"] == gu_pet.MODE_COMBAT else gu_pet.MODE_COMBAT
        self.db.update_gu_pet(pet_id, mode=new_mode)
        self.db.set_last_gu_pet_mode_switch_ts(user_id, now)
        label = "Combat" if new_mode == gu_pet.MODE_COMBAT else "Cultivation"
        emoji = "⚔️" if new_mode == gu_pet.MODE_COMBAT else "📿"
        return {"ok": True, "message": f"{emoji} Your Gu Pet switches to **{label} Mode**.", "mode": new_mode}

    def _drain_active_gu_pet_combat_dispatch(self, user_id: int, player: Optional[dict] = None):
        """Combat Mode's own per-dispatch Gu Pet upkeep (see apply_encounter_start_bonuses,
        the single "once per new encounter" hook this rides): drains a flat amount of satiety
        (see gu_pet.SATIETY_DRAIN_PER_COMBAT_DISPATCH), settling the pet first (see
        _settle_gu_pet_satiety) so the time anchor stays fresh even for a pet that's
        dispatched often but never has its Status tab opened. Also grants Crag-Shell Turtle's
        own "shields you" role_text here -- reuses the SAME encounter-start shield mechanism
        accessories with an encounter_shield effect already grant (see
        apply_encounter_start_bonuses' own add_buff call just above its call to this method),
        rather than building a new HP-threshold proc system from scratch."""
        player = player or self.db.get_player_row(user_id)
        if not player or not player["active_gu_pet_id"]:
            return
        pet = self.db.get_gu_pet(player["active_gu_pet_id"])
        if pet is None or pet["owner_id"] != user_id:
            return
        pet = self._settle_gu_pet_satiety(pet)
        if pet["stage"] != gu_pet.STAGE_MATURE or pet["mode"] != gu_pet.MODE_COMBAT:
            return
        new_satiety = max(0.0, pet["satiety"] - gu_pet.SATIETY_DRAIN_PER_COMBAT_DISPATCH)
        self.db.update_gu_pet(pet["pet_id"], satiety=new_satiety)
        if pet["species"] == gu_pet.SPECIES_CRAG_SHELL_TURTLE:
            satiety_mult, _ = gu_pet.satiety_band(new_satiety)
            combat_mult = gu_pet.rank_scaling(pet["rank"])["combat_multiplier"]
            def_bonus_pct = gu_pet.TURTLE_SHIELD_DEF_PCT_BASE * combat_mult * satiety_mult
            if def_bonus_pct > 0:
                self.db.add_buff(
                    user_id, "Crag-Shell Turtle's Shell", 0, gu_pet.TURTLE_SHIELD_DURATION_SECONDS,
                    def_bonus=def_bonus_pct * 100,
                )

    # -- Killer Move: assemble a core Gu + 10 component Gu into a procedurally-generated
    # active ability (see game/killer_move_gen.py / game/gu_types.py / /killer_move) --
    # additive alongside the gu_ability equipment slot above, not a replacement of it. -------

    KILLER_MOVE_COMPONENT_COUNT = 10
    KILLER_MOVE_SWAP_COOLDOWN_SECONDS = 600

    def assemble_killer_move(self, user_id: int, name: str, slot: str, core_gu_name: str, component_gu_names: list) -> dict:
        """Consumes core_gu_name + all KILLER_MOVE_COMPONENT_COUNT component_gu_names (a
        component name may repeat if owned in that quantity) to create one new Killer Move.
        Returns {"ok": False, "reason": ...} or {"ok": True, "killer_move": {...}}."""
        self.db.get_or_create_player(user_id, name)
        if slot not in ("combat", "support"):
            return {"ok": False, "reason": "Invalid Killer Move slot."}
        if len(component_gu_names) != self.KILLER_MOVE_COMPONENT_COUNT:
            return {"ok": False, "reason": f"You need exactly {self.KILLER_MOVE_COMPONENT_COUNT} component Gu (chose {len(component_gu_names)})."}

        core_gear = equipment.EQUIPMENT.get(core_gu_name)
        if core_gear is None or core_gear.slot_type != "Gu":
            return {"ok": False, "reason": f"**{core_gu_name}** isn't a Gu."}
        # gu_quality_for (not raw parse_gu_name) so flat single-instance Gu with a real rank
        # (World Boss Gu -- see world_boss.py's own registration comment) can anchor a move
        # too, not just tiered/canon Family (Quality) items.
        core_quality = equipment.gu_quality_for(core_gu_name)
        if core_quality is None:
            return {
                "ok": False,
                "reason": f"**{core_gu_name}** has no quality tier and can't anchor a Killer Move as its core "
                          "-- pick a tiered, canon, or World Boss Gu instead (it can still be one of your 10 components).",
            }
        for component_name in component_gu_names:
            component_gear = equipment.EQUIPMENT.get(component_name)
            if component_gear is None or component_gear.slot_type != "Gu":
                return {"ok": False, "reason": f"**{component_name}** isn't a Gu."}

        # Verify availability of ALL 11 before removing any -- mirrors craft_gear's
        # verify-then-loop-remove ordering, never a partial consumption.
        needed: Dict[str, int] = {core_gu_name: 1}
        for component_name in component_gu_names:
            needed[component_name] = needed.get(component_name, 0) + 1
        inventory = self.db.get_inventory(user_id)
        missing = {item_name: qty for item_name, qty in needed.items() if inventory.get(item_name, 0) < qty}
        if missing:
            missing_text = ", ".join(f"{qty}x {item_name} (have {inventory.get(item_name, 0)})" for item_name, qty in missing.items())
            return {"ok": False, "reason": f"Missing: {missing_text}."}

        move_tier = killer_move_gen.MOVE_TIER_BY_QUALITY[core_quality]
        primary_type = gu_types.gu_type_for(core_gu_name)
        component_types = [gu_types.gu_type_for(n) for n in component_gu_names]
        harmony = killer_move_gen.calculate_harmony(primary_type, component_types)
        kind = killer_move_gen.dominant_kind(component_types, primary_type)

        expected_kinds = ("damage", "buff") if slot == "combat" else ("essence", "cultivation", "loot")
        if kind not in expected_kinds:
            other_slot = "Support" if slot == "combat" else "Combat"
            return {
                "ok": False,
                "reason": f"This mix of Gu produces a **{kind}** Killer Move, which belongs in your "
                          f"{other_slot} slot instead -- try assembling it there.",
            }

        # gu_quality_for, not raw parse_gu_name -- see the core_quality lookup above for why.
        component_qualities = [equipment.gu_quality_for(n) for n in component_gu_names]
        rng = random.Random()
        if slot == "combat":
            effects = killer_move_gen.roll_combat_effects(kind, move_tier, harmony, component_qualities, rng)
        else:
            effects = killer_move_gen.roll_support_effects(kind, move_tier, harmony, component_qualities, rng)
        move_name = killer_move_gen.generate_killer_move_name(primary_type, rng)

        for item_name, qty in needed.items():
            self.db.remove_item(user_id, item_name, qty)

        killer_move_id = self.db.create_killer_move(user_id, {
            "slot": slot, "kind": kind, "name": move_name, "move_tier": move_tier,
            "primary_type": primary_type, "harmony": harmony,
            "qi_cost_pct": killer_move_gen.QI_COST_PCT_BY_TIER[move_tier], "effects": effects,
        })
        return {"ok": True, "killer_move": self.db.get_killer_move(killer_move_id)}

    def get_player_killer_moves(self, user_id: int) -> list:
        return self.db.get_player_killer_moves(user_id)

    def get_equipped_killer_move(self, player: dict, slot: str) -> Optional[dict]:
        """Read-only lookup, mirrors hunt.py's own _equipped_gu() shape. Deliberately doesn't
        touch qi/DB state itself -- hunt/raid/pvp track battle_qi as live in-memory state
        during an encounter (same convention Empower/Gu-ability costs already use), so those
        views handle their own qi check/deduction and only call back into GameManager
        (apply_killer_move_buff below) for the parts that need no view-local state."""
        # player is normally a raw sqlite3.Row (get_or_create_player's return type), which
        # supports player[column] but not .get() -- indexing directly like every other player
        # field read in this codebase, not the dict-style .get() that would raise here.
        column = "equipped_combat_killer_move_id" if slot == "combat" else "equipped_support_killer_move_id"
        move_id = player[column]
        return self.db.get_killer_move(move_id) if move_id else None

    def killer_move_qi_cost(self, player: dict, move: dict) -> int:
        return round(player["qi_stat"] * move["qi_cost_pct"])

    def apply_killer_move_buff(self, user_id: int, player: dict, move: dict):
        """Applies a buff-kind Combat Killer Move's effects via the standard buffs table --
        shared by every combat view so the %-of-current-stat -> flat-bonus math (same
        convention Epic Physique's Breakthrough Vigor already uses) and the lifesteal
        special_bonuses translation live in exactly one place."""
        effects = move["effects"]
        self.db.add_buff(
            user_id, move["name"], 0, effects["duration_seconds"],
            str_bonus=round(player["str_stat"] * effects.get("str_pct", 0)),
            atk_bonus=round(player["atk_stat"] * effects.get("atk_pct", 0)),
            def_bonus=round(player["def_stat"] * effects.get("def_pct", 0)),
            special_bonuses={"lifesteal_percent": effects["lifesteal_pct"]} if "lifesteal_pct" in effects else None,
        )

    def equip_killer_move(self, user_id: int, name: str, killer_move_id: int) -> tuple:
        player = self.db.get_or_create_player(user_id, name)
        move = self.db.get_killer_move(killer_move_id)
        if move is None or move["owner_id"] != user_id:
            return False, "You don't own that Killer Move."
        remaining = self._check_cooldown(player, "last_killer_move_swap_ts", self.KILLER_MOVE_SWAP_COOLDOWN_SECONDS)
        if remaining > 0:
            from .ui_utils import format_duration
            return False, f"Your Killer Moves are still settling from your last change — try again in {format_duration(remaining)}."
        self.db.set_equipped_killer_move(user_id, move["slot"], killer_move_id)
        self.db.set_timestamp_column(user_id, "last_killer_move_swap_ts", int(time.time()))
        return True, f"Equipped **{move['name']}** as your {move['slot']} Killer Move."

    def unequip_killer_move(self, user_id: int, name: str, slot: str) -> tuple:
        self.db.get_or_create_player(user_id, name)
        if slot not in ("combat", "support"):
            return False, "Invalid Killer Move slot."
        self.db.set_equipped_killer_move(user_id, slot, None)
        return True, f"Unequipped your {slot} Killer Move."

    def activate_support_killer_move(self, user_id: int, name: str) -> tuple:
        """/killer_move's standalone activation for the Support slot -- modeled directly on
        activate_accessory_artifact's branches. Unlike the Combat slot (spent from a combat
        view's own live battle_qi tracking), this settles/deducts battle_qi straight against
        the DB since there's no in-progress encounter to track it locally."""
        player = self.db.get_or_create_player(user_id, name)
        move = self.get_equipped_killer_move(player, "support")
        if move is None:
            return False, "You have no Killer Move equipped in your Support slot."
        settled = self.db.settle_battle_qi(user_id)
        qi_cost = self.killer_move_qi_cost(settled, move)
        # Equipped gear's flat qi_stat bonus (Artifacts, crafted gear's qi_pct, ...) is folded
        # in as a live overlay on top of settled["battle_qi"] here, same convention hunt.py's
        # own in-combat qi tracking already uses for self.player_qi (see HuntView.__init__) --
        # otherwise this affordability check silently disagreed with the battle-qi number a
        # player actually sees in combat, which could show "plenty of Qi" while this still
        # said "not enough". qi_cost itself is left on the raw qi_stat basis, same as the
        # Combat-slot version's own killer_move_qi_cost call (hunt.py's _on_killer_move) --
        # only the "how much do you currently have" side was the mismatch being fixed here.
        qi_bonus = self.compute_equipment_bonuses(user_id)["stats"]["qi_stat"]
        current_qi = settled["battle_qi"] + qi_bonus
        if current_qi < qi_cost:
            return False, f"Not enough Qi to use **{move['name']}** (needs {format_number(qi_cost)}, you have {format_number(current_qi, decimals=0)})."
        self.db.set_battle_qi(user_id, max(0.0, current_qi - qi_cost - qi_bonus))

        effects = move["effects"]
        if move["kind"] == "essence":
            # allow_overflow=True -- a Killer Move is a deliberate, cooldown/Qi-gated activation
            # (unlike the passive equipment-bonus top-ups restore_essence_percent's docstring
            # warns off overflow for), so it shouldn't get partially wasted just because the
            # player wasn't already sitting well below their essence cap, matching the same
            # never-waste-it precedent items.py's essence pills/crystals already use.
            gained = self._restore_essence_pct(user_id, effects["pct"], allow_overflow=True)
            return True, f"**{move['name']}**: restored {format_number(gained, decimals=0)} primeval essence."
        if move["kind"] == "cultivation":
            self.db.add_buff(user_id, move["name"], effects["pct"], effects["duration_seconds"])
            return True, f"**{move['name']}**: cultivation speed surges by {effects['pct'] * 100:.0f}% for a while!"
        # kind == "loot"
        self.db.add_buff(
            user_id, move["name"], 0, effects["duration_seconds"],
            special_bonuses={"loot_chance_bonus_pct": effects["pct"]},
        )
        return True, f"**{move['name']}**: your luck surges by {effects['pct'] * 100:.0f}% for a while!"

    def sell_item(self, user_id: int, name: str, item_name: str, quantity: int = 1):
        """NPC vendor buys back an ordinary stackable item (Healing/Pills/Materials, or a
        catalog Gu) for spirit stones -- the /sell "garbage dump" command. Returns
        (ok, message, stones_gained). Gu routes straight into breakdown_gu (same pricing, one
        source of truth, not a second formula); non-Gu catalog Equipment has no vendor price
        here by design -- crafted_gear/accessories/avatar gear each already have their own
        tuned dismantle/salvage/sell path elsewhere in /sell, and duplicate starter gear isn't
        a real clutter problem the way stacked Materials/Pills are."""
        self.db.get_or_create_player(user_id, name)
        gear = equipment.EQUIPMENT.get(item_name)
        if gear is not None:
            if gear.slot_type != "Gu":
                return False, f"**{item_name}** can't be sold here — try `/trade` to pass it to another player.", 0
            return self.breakdown_gu(user_id, name, item_name, quantity)
        if item_name not in items.ITEMS:
            return False, "That's not a sellable item.", 0
        owned = self.db.get_inventory(user_id).get(item_name, 0)
        quantity = min(quantity, owned)
        if quantity <= 0:
            return False, f"You don't own a **{item_name}** to sell.", 0
        self.db.remove_item(user_id, item_name, quantity)
        stones = items.sell_value(item_name) * quantity
        self.db.add_spirit_stones(user_id, stones)
        return True, f"Sold {quantity}x **{item_name}** for **{format_number(stones)}** 🪙 spirit stones.", stones

    # -- Professions: /study --------------------------------------------------

    def study(self, user_id: int, name: str, profession: str) -> dict:
        """Advances profession study state one step. Returns a dict describing what
        happened — outcome is one of:
          "maxed"       — already Dao Master, nothing to do.
          "busy"        — already studying a DIFFERENT profession.
          "started"     — began studying (nothing was in progress).
          "in_progress" — already studying this profession, not done yet.
          "leveled_up"  — studying this profession completed; rank advanced by 1.
        """
        player = self.db.get_or_create_player(user_id, name)
        rank_column = professions.RANK_COLUMN[profession]
        current_rank = player[rank_column]

        if current_rank >= professions.MAX_RANK_INDEX:
            return {"outcome": "maxed", "profession": profession, "rank": current_rank}

        if player["studying_profession"] == profession:
            # A Human-family root's profession_study_speed_pct (see character_data.
            # CharacterTraitSpec) — applies to whichever profession the player is actively
            # studying, matching the design brief's "one profession may be studied faster"
            # without needing a separate "which one" selection UI.
            required_hours = professions.hours_required(current_rank) * (1 - self._trait_bonus(player, "profession_study_speed_pct"))
            elapsed_hours = (time.time() - player["studying_started_ts"]) / 3600
            if elapsed_hours >= required_hours:
                player = self.db.complete_study(user_id, rank_column)
                return {"outcome": "leveled_up", "profession": profession, "new_rank": player[rank_column]}
            return {
                "outcome": "in_progress", "profession": profession,
                "hours_required": required_hours, "hours_elapsed": elapsed_hours,
            }

        if player["studying_profession"]:
            return {"outcome": "busy", "studying": player["studying_profession"]}

        self.db.start_study(user_id, profession)
        return {"outcome": "started", "profession": profession, "hours_required": professions.hours_required(current_rank)}

    def cancel_study(self, user_id: int, name: str) -> dict:
        """Abandons whatever profession is currently being studied, losing all progress
        toward that rank (studying_started_ts resets — there's no partial credit banked
        anywhere else to preserve). Returns {"outcome": "not_studying"} or {"outcome":
        "cancelled", "profession", "hours_lost"}."""
        player = self.db.get_or_create_player(user_id, name)
        profession = player["studying_profession"]
        if not profession:
            return {"outcome": "not_studying"}
        hours_lost = max(0.0, (time.time() - player["studying_started_ts"]) / 3600)
        self.db.cancel_study(user_id)
        return {"outcome": "cancelled", "profession": profession, "hours_lost": hours_lost}

    def check_and_complete_ready_studies(self) -> list:
        """Periodic sweep (see GameCog.study_tick) -- auto-completes any profession study
        that's crossed 100% progress, without the player needing to manually re-run /study
        to claim it (per explicit request: study used to just sit at "done" until the player
        happened to check back in). Mirrors study()'s own completion math exactly (including
        the Human-family root's profession_study_speed_pct), just applied across every
        currently-studying player instead of one. Returns [{"user_id", "name", "profession",
        "new_rank"}, ...] for every completion this sweep triggered, for the caller to DM."""
        completed = []
        for player in self.db.get_players_currently_studying():
            profession = player["studying_profession"]
            rank_column = professions.RANK_COLUMN[profession]
            current_rank = player[rank_column]
            if current_rank >= professions.MAX_RANK_INDEX:
                continue  # shouldn't normally happen (study() itself blocks starting past max) -- never crash on it
            required_hours = professions.hours_required(current_rank) * (1 - self._trait_bonus(player, "profession_study_speed_pct"))
            elapsed_hours = (time.time() - player["studying_started_ts"]) / 3600
            if elapsed_hours >= required_hours:
                updated = self.db.complete_study(player["user_id"], rank_column)
                completed.append({
                    "user_id": player["user_id"], "name": player["name"], "profession": profession,
                    "new_rank": updated[rank_column],
                })
        return completed

    def grant_profession_rank(self, user_id: int, name: str, profession: str, amount: int = 1) -> dict:
        """/grant_profession_rank (admin) -- flat +amount to a profession's rank, clamped at
        Dao Master. Deliberately independent of study()/complete_study(): does NOT touch
        studying_profession/studying_started_ts at all, so granting a rank never silently
        cancels unrelated in-progress study (see GameDatabase.add_profession_rank's own
        docstring). Returns {"profession", "old_rank", "new_rank", "capped"}."""
        player = self.db.get_or_create_player(user_id, name)
        rank_column = professions.RANK_COLUMN[profession]
        old_rank = player[rank_column]
        new_rank = self.db.add_profession_rank(user_id, rank_column, amount, professions.MAX_RANK_INDEX)
        return {
            "profession": profession, "old_rank": old_rank, "new_rank": new_rank,
            "capped": old_rank + amount > professions.MAX_RANK_INDEX,
        }

    # -- World region: /region (see world_regions.py) ---------------------------------------
    # A mortal-realm character's chosen geographic zone -- separate from search_data's own
    # per-realm "region" (danger tier). Eligibility and every bonus number lives in
    # world_regions.py; this class only reads it and applies it at the right call sites.

    def get_world_region_status(self, user_id: int, name: str) -> dict:
        player = self.db.get_or_create_player(user_id, name)
        great_realm_index = realms.STAGES[player["realm_index"]].great_realm_index
        destination = player["world_region_travel_destination"]
        travel_remaining = 0
        if destination:
            elapsed = int(time.time()) - player["world_region_travel_started_ts"]
            travel_remaining = max(0, world_regions.WORLD_REGION_TRAVEL_SECONDS - elapsed)
        return {
            "player": player,
            "requires_travel": world_regions.requires_travel(great_realm_index),
            "current": player["world_region"],
            "traveling_to": destination,
            "travel_remaining_seconds": travel_remaining,
            "remaining_seconds": self._check_cooldown(player, "last_world_region_change_ts", world_regions.REGION_CHANGE_COOLDOWN_SECONDS),
        }

    def set_world_region(self, user_id: int, name: str, region_key: str) -> dict:
        status = self.get_world_region_status(user_id, name)
        if region_key not in world_regions.WORLD_REGIONS:
            return {"ok": False, "reason": "unknown_region"}
        if status["traveling_to"]:
            return {"ok": False, "reason": "already_traveling", "travel_remaining_seconds": status["travel_remaining_seconds"]}
        if region_key == status["current"]:
            return {"ok": False, "reason": "already_there"}
        # Fixed Immortal Travel Gu (see world_boss.py): "instantly teleport to unlocked
        # regions" -- bypasses REGION_CHANGE_COOLDOWN_SECONDS below Nascent Soul, and the real
        # travel delay at Spirit Severing+.
        gu_name = self.db.get_equipped(user_id).get("gu_ability")
        if gu_name == "Fixed Immortal Travel Gu":
            self.db.set_world_region(user_id, region_key)
            return {"ok": True, "region": world_regions.WORLD_REGIONS[region_key], "instant": True}
        if not status["requires_travel"]:
            if status["current"] and status["remaining_seconds"] > 0:
                return {"ok": False, "reason": "cooldown", "remaining_seconds": status["remaining_seconds"]}
            self.db.set_world_region(user_id, region_key)
            return {"ok": True, "region": world_regions.WORLD_REGIONS[region_key], "instant": True}
        self.db.start_world_region_travel(user_id, region_key)
        return {
            "ok": True, "region": world_regions.WORLD_REGIONS[region_key], "instant": False,
            "travel_seconds": world_regions.WORLD_REGION_TRAVEL_SECONDS,
        }

    def check_and_complete_world_region_travel(self) -> list:
        """Periodic sweep (see GameCog.world_region_travel_tick) -- auto-completes any
        Spirit-Severing+ region journey whose WORLD_REGION_TRAVEL_SECONDS has actually
        elapsed. Returns a list of {"user_id", "region"} for each completion, so the caller
        can DM each player (mirrors check_and_complete_white_heaven_travel's own shape)."""
        completed = []
        now = int(time.time())
        for player in self.db.get_players_with_pending_world_region_travel():
            if now - player["world_region_travel_started_ts"] < world_regions.WORLD_REGION_TRAVEL_SECONDS:
                continue
            destination_key = player["world_region_travel_destination"]
            self.db.complete_world_region_travel(player["user_id"], destination_key)
            completed.append({"user_id": player["user_id"], "region": world_regions.WORLD_REGIONS[destination_key]})
        return completed

    def _region_bonus_dict(self, player) -> dict:
        return world_regions.REGION_BONUSES.get(player["world_region"], {})

    def _player_location_rank(self, player) -> int:
        return realms.STAGES[player["realm_index"]].great_realm_index + 1

    def maybe_trigger_region_discovery(self, user_id: int, name: str) -> Optional[dict]:
        """Called once per successful /mine, /gather, /explore, /hunt, or /raid action --
        "special inheritances, battlefields, and dream realms... found when taking actions in
        these zones." Never overwrites an already-active discovery. Returns
        {"type", "theme", "rank"} on a hit, else None."""
        player = self.db.get_or_create_player(user_id, name)
        if player["active_discovery_id"]:
            return None
        bonus = self._region_bonus_dict(player)
        if not bonus or random.random() >= bonus["action_discovery_chance"]:
            return None
        rng = random.Random()
        discovery_type = discovery_gen.weighted_choice(bonus["discovery_type_weights"], rng)
        location_rank = self._player_location_rank(player)
        if discovery_type == "inheritance":
            effective_luck = self._effective_luck(user_id, player)
            rank = world_regions.roll_region_inheritance_rank(effective_luck, rng)
            theme = rng.choice(search_data.INHERITANCE_THEMES)
        elif discovery_type == "battlefield":
            rank = location_rank
            theme = rng.choice(search_data.BATTLEFIELD_THEMES)
        else:  # region_dream_realm
            rank = location_rank
            theme = rng.choice(search_data.REGION_DREAM_REALM_THEMES)
        difficulty = discovery_gen.roll_difficulty(rng, quality_bias=self._trait_bonus(player, "discovery_quality_bias_pct"))
        expires = int(time.time()) + search_data.DISCOVERY_EXPIRY_SECONDS[discovery_type]
        self.db.create_discovery(user_id, {
            "type": discovery_type, "theme": theme["name"], "rank": rank,
            "difficulty": difficulty, "seed": rng.randrange(1, 2**31), "expires_at": expires,
        })
        return {"type": discovery_type, "theme": theme["name"], "rank": rank}

    def region_encounter_modifiers(self, user_id: int, name: str) -> dict:
        """Called once when a /hunt or /raid begins. Northern Plains makes every monster
        tougher with better loot; Eastern Sea/Western Desert/Central Continent instead roll a
        chance for a "hoard guardian" encounter -- a tougher monster guaranteed to also drop a
        themed bonus reward on victory. Returns {"stat_multiplier", "loot_chance_bonus_pct",
        "hoard_label": str|None, "hoard_reward": dict|None} -- hoard_reward, if set, is a
        reward dict ready for GameManager.grant_reward."""
        player = self.db.get_or_create_player(user_id, name)
        bonus = self._region_bonus_dict(player)
        stat_multiplier = bonus.get("monster_stat_multiplier", 1.0)
        loot_chance_bonus_pct = bonus.get("loot_chance_bonus_pct", 0.0)
        hoard_label, hoard_reward = None, None
        hoard_chance = bonus.get("hoard_chance", 0.0)
        if hoard_chance and random.random() < hoard_chance:
            stat_multiplier = max(stat_multiplier, bonus.get("hoard_stat_multiplier", 1.0))
            location_rank = self._player_location_rank(player)
            region_key = player["world_region"]
            rng = random.Random()
            if region_key == "eastern_sea":
                hoard_label = "a hoard of herbs, ore, and monster materials"
                tier = max(1, min(7, location_rank))
                item_name = rng.choice([f"Tier {tier} Herb", f"Tier {tier} Ore", f"Tier {tier} Beast Material"])
                hoard_reward = {"kind": "item", "item_name": item_name, "quantity": rng.randint(3, 6)}
            elif region_key == "western_desert":
                hoard_label = "a hoard of spirit stones"
                base = {1: 150, 2: 300, 3: 500, 4: 800}.get(location_rank, 800)
                hoard_reward = {"kind": "stones", "amount": rng.randint(base, round(base * 1.6))}
            elif region_key == "central_continent":
                hoard_label = "a completed manual's worth of pages"
                pool = [p for p in manual_data.PAGES.values() if p.rank <= location_rank + 1]
                page_ids = [rng.choice(pool).page_id for _ in range(min(3, len(pool)))] if pool else []
                hoard_reward = {"kind": "pages", "page_ids": page_ids}
        return {
            "stat_multiplier": stat_multiplier, "loot_chance_bonus_pct": loot_chance_bonus_pct,
            "hoard_label": hoard_label, "hoard_reward": hoard_reward,
        }

    def grant_reward(self, user_id: int, name: str, reward: dict) -> str:
        """Public wrapper around _grant_reward for callers outside this module (hunt/raid
        hoard bonus loot, battlefield wave/final rewards, region dream realm rewards) that
        already have a resolved reward dict from discovery_gen.generate_loot or a hand-built
        region hoard reward."""
        return self._grant_reward(user_id, name, reward)

    # -- White Heaven: /white_heaven (see game/white_heaven.py) -- a Dao Seeking+ endgame
    # region reached via a real 1h travel delay each way, auto-completed by a background
    # tick (see check_and_complete_white_heaven_travel) rather than manually claimed, since
    # there's nothing to claim here -- just a location flip. Deliberately separate from
    # world_regions.py above: that's an instant-switch mortal-realm playstyle choice, this is
    # a real journey gated at the opposite end of the realm ladder.

    # Heaven's Wing Gu (see game/content/canon_gu_white_heaven.py) -- "faster White Heaven
    # travel time" is checked live (not snapshotted at trip start) since equipping/
    # unequipping mid-trip to change your own travel time isn't a meaningful exploit, and
    # this avoids a second persisted "effective duration for this specific trip" column.
    HEAVENS_WING_GU_TRAVEL_DISCOUNT_PCT = 0.5

    def _white_heaven_travel_seconds(self, user_id: int) -> int:
        gu_name = self.db.get_equipped(user_id).get("gu_ability")
        # Equipped Gu names carry a "(Quality)" suffix (e.g. "Heaven's Wing Gu (Immortal)")
        # -- parse_gu_name strips it to recover the bare family name, falling back to the
        # raw name for flat/unsuffixed items (same gu_types.gu_type_for convention).
        family = equipment.parse_gu_name(gu_name)[0] or gu_name if gu_name else None
        if family == "Heaven's Wing Gu":
            return round(white_heaven.WHITE_HEAVEN_TRAVEL_SECONDS * (1 - self.HEAVENS_WING_GU_TRAVEL_DISCOUNT_PCT))
        return white_heaven.WHITE_HEAVEN_TRAVEL_SECONDS

    def get_white_heaven_status(self, user_id: int, name: str) -> dict:
        player = self.db.get_or_create_player(user_id, name)
        great_realm_index = realms.STAGES[player["realm_index"]].great_realm_index
        started = player["white_heaven_travel_started_ts"]
        remaining = max(0, self._white_heaven_travel_seconds(user_id) - (int(time.time()) - started)) if started else 0
        return {
            "player": player,
            "eligible": white_heaven.is_eligible(great_realm_index),
            "status": player["white_heaven_status"],
            "remaining_seconds": remaining,
        }

    def start_white_heaven_travel(self, user_id: int, name: str) -> dict:
        """'Depart for White Heaven' -- only from 'away', only realm-eligible, only when no
        trip is already in progress."""
        status = self.get_white_heaven_status(user_id, name)
        if not status["eligible"]:
            return {"ok": False, "reason": "ineligible"}
        if status["status"] != "away":
            return {"ok": False, "reason": "busy", "status": status["status"]}
        self.db.start_white_heaven_travel(user_id, "traveling_there")
        return {"ok": True}

    def start_white_heaven_return(self, user_id: int, name: str) -> dict:
        """'Return Home' -- only from 'present', only when no trip is already in progress."""
        status = self.get_white_heaven_status(user_id, name)
        if status["status"] != "present":
            return {"ok": False, "reason": "not_present", "status": status["status"]}
        self.db.start_white_heaven_travel(user_id, "traveling_back")
        return {"ok": True}

    def check_and_complete_white_heaven_travel(self) -> list:
        """Periodic sweep (see GameCog.white_heaven_tick) -- auto-completes any White Heaven
        trip that's crossed WHITE_HEAVEN_TRAVEL_SECONDS without the player needing to check
        back in themselves (mirrors check_and_complete_ready_studies' own auto-complete
        shape, not split_body's manual-claim shape). Returns [{"user_id", "name", "arrived"},
        ...] for every completion this sweep triggered, for the caller to DM -- arrived=True
        means they just landed in White Heaven, False means they just made it back home."""
        completed = []
        now = int(time.time())
        for player in self.db.get_players_with_pending_white_heaven_travel():
            if now - player["white_heaven_travel_started_ts"] < self._white_heaven_travel_seconds(player["user_id"]):
                continue
            arrived = player["white_heaven_status"] == "traveling_there"
            self.db.complete_white_heaven_travel(player["user_id"], "present" if arrived else "away")
            completed.append({"user_id": player["user_id"], "name": player["name"], "arrived": arrived})
        return completed

    # -- Black Heaven: /black_heaven (see game/black_heaven.py) -- a second, deadlier Dao
    # Seeking+ endgame region alongside White Heaven, reached via a real 2h travel delay each
    # way (double White Heaven's own 1h). Same eligibility gate and auto-complete-on-sweep
    # shape as White Heaven's own travel block above -- unlike White Heaven, /hunt and /raid
    # are untouched while present; the entire region is /search_black_heaven (see
    # ACTIVE_BLACK_HEAVEN_SEARCH_STALE_SECONDS/has_active_black_heaven_search below, and the
    # full bubble-board block added in a later phase).

    # No travel-discount Gu exists in this batch (unlike White Heaven's Heaven's Wing Gu), so
    # this is a flat passthrough rather than an equipped-Gu lookup.
    def _black_heaven_travel_seconds(self, user_id: int) -> int:
        return black_heaven.BLACK_HEAVEN_TRAVEL_SECONDS

    def get_black_heaven_status(self, user_id: int, name: str) -> dict:
        player = self.db.get_or_create_player(user_id, name)
        great_realm_index = realms.STAGES[player["realm_index"]].great_realm_index
        started = player["black_heaven_travel_started_ts"]
        remaining = max(0, self._black_heaven_travel_seconds(user_id) - (int(time.time()) - started)) if started else 0
        return {
            "player": player,
            "eligible": black_heaven.is_eligible(great_realm_index),
            "status": player["black_heaven_status"],
            "remaining_seconds": remaining,
        }

    def start_black_heaven_travel(self, user_id: int, name: str) -> dict:
        """'Depart for Black Heaven' -- only from 'away', only realm-eligible, only when no
        trip is already in progress."""
        status = self.get_black_heaven_status(user_id, name)
        if not status["eligible"]:
            return {"ok": False, "reason": "ineligible"}
        if status["status"] != "away":
            return {"ok": False, "reason": "busy", "status": status["status"]}
        self.db.start_black_heaven_travel(user_id, "traveling_there")
        return {"ok": True}

    def start_black_heaven_return(self, user_id: int, name: str) -> dict:
        """'Return Home' -- only from 'present', only when no trip is already in progress,
        and only when no Search Black Heaven run is currently active (mirrors /inheritance_
        ground's own "finish or abandon first" gating shape -- can't wander off mid-encounter)."""
        status = self.get_black_heaven_status(user_id, name)
        if status["status"] != "present":
            return {"ok": False, "reason": "not_present", "status": status["status"]}
        if self.has_active_black_heaven_search(status["player"]):
            return {"ok": False, "reason": "active_search"}
        self.db.start_black_heaven_travel(user_id, "traveling_back")
        return {"ok": True}

    def check_and_complete_black_heaven_travel(self) -> list:
        """Periodic sweep (see GameCog.black_heaven_tick) -- auto-completes any Black Heaven
        trip that's crossed BLACK_HEAVEN_TRAVEL_SECONDS, mirroring check_and_complete_white_
        heaven_travel exactly. Returns [{"user_id", "name", "arrived"}, ...] for the caller to
        DM."""
        completed = []
        now = int(time.time())
        for player in self.db.get_players_with_pending_black_heaven_travel():
            if now - player["black_heaven_travel_started_ts"] < self._black_heaven_travel_seconds(player["user_id"]):
                continue
            arrived = player["black_heaven_status"] == "traveling_there"
            self.db.complete_black_heaven_travel(player["user_id"], "present" if arrived else "away")
            completed.append({"user_id": player["user_id"], "name": player["name"], "arrived": arrived})
        return completed

    # -- Search Black Heaven's own "one at a time" busy flag + leader-only cooldown (see
    # game/black_heaven_search_view.py) -- same shape as Inheritance Ground's own pair above.
    # The full bubble-board generation/reward-grant block is added in a later phase; this much
    # is needed now so start_black_heaven_return (above) can refuse to let a player wander off
    # mid-Search.
    ACTIVE_BLACK_HEAVEN_SEARCH_STALE_SECONDS = 2 * 3600
    BLACK_HEAVEN_SEARCH_COOLDOWN_SECONDS = 4 * 3600
    # A leader could previously fire off unlimited BlackHeavenSearchLobbyView invites back to
    # back (nothing gated a NEW invite while a PRIOR one was still pending -- only
    # has_active_black_heaven_search/the leader's own cooldown, both of which only become true
    # once a lobby actually RESOLVES) and accept them one at a time later, each starting its
    # own independent run and its own free rewards. Fixed by requiring the leader clear this
    # flag (accept/decline/cancel/timeout all clear it, see BlackHeavenSearchLobbyView) before
    # sending another. Stale-guard window comfortably exceeds the lobby's own 300s Discord view
    # timeout, covering a redeploy mid-invite the same way ACTIVE_BLACK_HEAVEN_SEARCH_STALE_
    # SECONDS covers one mid-run.
    BLACK_HEAVEN_SEARCH_INVITE_PENDING_STALE_SECONDS = 600

    def has_pending_black_heaven_search_invite(self, player: dict) -> bool:
        started = player["black_heaven_search_invite_pending_ts"]
        return bool(started) and (time.time() - started) < self.BLACK_HEAVEN_SEARCH_INVITE_PENDING_STALE_SECONDS

    def set_black_heaven_search_invite_pending(self, leader_id: int):
        self.db.set_black_heaven_search_invite_pending(leader_id, int(time.time()))

    def clear_black_heaven_search_invite_pending(self, leader_id: int):
        self.db.set_black_heaven_search_invite_pending(leader_id, 0)

    def has_active_black_heaven_search(self, player: dict) -> bool:
        started = player["active_black_heaven_started_ts"]
        return bool(started) and (time.time() - started) < self.ACTIVE_BLACK_HEAVEN_SEARCH_STALE_SECONDS

    # -- Search Black Heaven's own battle-bubble roster (see content/monsters/black_heaven.py)
    # -- weighted by TIER same as Inheritance Ground's own Blood Sea Ancestor roll
    # (BLOOD_SEA_RARITY_TIER_WEIGHT above), each rarer tier both tougher (that file's own
    # _RARITY_MULTIPLIER) and better-rewarding below. Steeper per-battle escalation than
    # Inheritance Ground's own 0.20 (BATTLE_STAT_MULTIPLIER_PER_BATTLE) -- fewer, scarier
    # fights per run, matching "very very strong mobs" / "could get absolutely destroyed".
    BLACK_HEAVEN_RARITY_TIER_WEIGHT = {"Common": 45, "Uncommon": 27, "Rare": 12, "Elite": 4}
    BLACK_HEAVEN_RARITY_CANON_GU_ENCOUNTER = {"Common": "normal", "Uncommon": "elite", "Rare": "mini_boss", "Elite": "world_boss"}
    # A small independent shot at one of the 15 Black Heaven canon Gu on a battle-bubble
    # victory (see content/canon_gu_black_heaven.py) -- these are drop_weight=0, so the
    # generic canon_gu.roll_canon_gu_drop call just above can never actually surface one
    # (mirrors White Heaven's own roll_white_heaven_bonus_gu problem/solution). Scaled by the
    # monster's own rarity tier so an Elite kill has meaningfully better odds than a Common one.
    BLACK_HEAVEN_RARITY_BONUS_GU_CHANCE = {"Common": 1 / 200, "Uncommon": 1 / 120, "Rare": 1 / 60, "Elite": 1 / 25}
    BLACK_HEAVEN_BATTLE_STAT_MULTIPLIER_PER_BATTLE = 0.35

    def roll_black_heaven_battle_monster(self, battle_number: int):
        """battle_number is 1-indexed (the Nth battle bubble revealed this Search run), scaled
        up progressively via dataclasses.replace -- mirrors roll_inheritance_ground_battle_
        monster's own "blood_sea_ancestor" branch exactly, just against Black Heaven's own
        fixed roster (there's only ever one Black Heaven, so no ground_key branching needed)."""
        rarities = list(black_heaven_monsters.ALL_MONSTERS_BY_RARITY)
        rarity = random.choices(rarities, weights=[self.BLACK_HEAVEN_RARITY_TIER_WEIGHT[r] for r in rarities])[0]
        base = random.choice(black_heaven_monsters.ALL_MONSTERS_BY_RARITY[rarity])
        multiplier = 1.0 + self.BLACK_HEAVEN_BATTLE_STAT_MULTIPLIER_PER_BATTLE * (battle_number - 1)
        if multiplier == 1.0:
            return base
        return dataclasses.replace(
            base,
            hp=max(1, round(base.hp * multiplier)), atk_stat=max(1, round(base.atk_stat * multiplier)),
            str_stat=max(1, round(base.str_stat * multiplier)), def_stat=max(1, round(base.def_stat * multiplier)),
            spd_stat=max(1, round(base.spd_stat * multiplier)),
        )

    def roll_black_heaven_battle_bonus_gu(self, rarity: str) -> Optional[str]:
        """Called once per team member on a battle-bubble victory (see grant_black_heaven_
        battle_loot below). Always rolls at Common quality/star 1, same "a newly obtained Gu
        starts at 1 star" convention every other drop mechanism in this codebase uses."""
        chance = self.BLACK_HEAVEN_RARITY_BONUS_GU_CHANCE.get(rarity, 0)
        if random.random() >= chance:
            return None
        name = random.choice(canon_gu_black_heaven.BLACK_HEAVEN_CANON_GU_NAMES)
        return equipment.gu_item_name(name, "Common")

    def grant_black_heaven_battle_loot(self, team: list, monster) -> list:
        """Called once a battle bubble's guardian is actually defeated -- one independent roll
        per team member: the monster's own beast-material drops (monsters.roll_loot, same as
        /hunt), a rarity-scaled shot at the generic canon-Gu roll, and a separate rarity-scaled
        shot at one of Black Heaven's own 15 Gu. Returns [(name, summary_text), ...]."""
        rarity = black_heaven_monsters.RARITY_BY_NAME.get(monster.name)
        results = []
        for user_id, name in team:
            material_loot = monsters.roll_loot(monster)
            for item_name, qty in material_loot.items():
                self.db.add_item(user_id, item_name, qty)
            parts = [f"{qty}x {item_name}" for item_name, qty in material_loot.items()]
            if rarity:
                canon_drop = canon_gu.roll_canon_gu_drop(monster.gu_rank, self.BLACK_HEAVEN_RARITY_CANON_GU_ENCOUNTER[rarity])
                if canon_drop:
                    self.db.add_item(user_id, canon_drop, 1)
                    parts.append(f"🐛 {canon_drop}")
                bonus_gu = self.roll_black_heaven_battle_bonus_gu(rarity)
                if bonus_gu:
                    self.db.add_item(user_id, bonus_gu, 1)
                    parts.append(f"🌑 {bonus_gu}")
            results.append((name, ", ".join(parts) if parts else "nothing this time"))
        return results

    def black_heaven_search_cooldown_remaining(self, player: dict) -> int:
        return self._check_cooldown(player, "last_black_heaven_search_ts", self.BLACK_HEAVEN_SEARCH_COOLDOWN_SECONDS)

    def check_black_heaven_search_eligibility(self, user_id: int, name: str) -> tuple:
        """Used both when the leader first invites AND when each invitee is about to accept --
        mirrors check_inheritance_ground_eligibility's own shape (re-checked fresh at both
        points, doesn't gate on the invitee's own cooldown), plus ONE real addition per
        explicit request: every invitee must ALSO currently be black_heaven_status == "present"
        -- unlike Inheritance Ground, which can invite anyone regardless of location, Search
        Black Heaven can only ever include players already there. Returns (ok, reason_code, 0)
        -- reason_code is one of "not_confirmed"/"already_active"/"not_present"/None (ok)."""
        player = self.db.get_or_create_player(user_id, name)
        if not player["character_confirmed"]:
            return False, "not_confirmed", 0
        if self.has_active_black_heaven_search(player):
            return False, "already_active", 0
        if player["black_heaven_status"] != "present":
            return False, "not_present", 0
        return True, None, 0

    def start_active_black_heaven_search(self, user_ids: list):
        self.db.start_active_black_heaven_bulk(user_ids, int(time.time()))

    def abandon_active_black_heaven_search(self, user_id: int):
        """Self-service escape hatch, same reasoning as abandon_active_inheritance_ground above."""
        self.db.clear_active_black_heaven_bulk([user_id])

    def finish_black_heaven_search_run(self, user_ids: list, leader_id: int):
        """Called at every terminal state (lobby cancelled/timed out before starting, board
        exhausted, or a battle-bubble wipe) -- releases the active flag for the WHOLE team, but
        only starts the cooldown for leader_id, same "invited teammates aren't gated behind
        someone else's run" reasoning as finish_inheritance_ground_run."""
        now = int(time.time())
        self.db.clear_active_black_heaven_bulk(user_ids)
        self.db.set_black_heaven_search_cooldown_bulk([leader_id], now)

    # -- Search Black Heaven's own bubble board -- same "fixed 20-bubble board, team_size only
    # affects how many the team gets to POP" shape generate_inheritance_ground_board uses, just
    # with Black Heaven's own category set per explicit request: nothing/ascension_pill/
    # essence_crystal/essence_pill/materials/immortal_notes as the weighted filler
    # (ascension_pill added 2026-08-14, immortal_notes added same day, both mirroring
    # Inheritance Ground's own bubble set), one guaranteed "gu" bubble (instead of Inheritance
    # Ground's "treasure") and BLACK_HEAVEN_MIN_BATTLE_BUBBLES (3, not 2) guaranteed "battle"
    # bubbles -- "very very strong mobs" gets more encounters, not just scarier ones.
    BLACK_HEAVEN_BOARD_SIZE = 20
    BLACK_HEAVEN_BUBBLES_PER_TEAM_MEMBER = 2
    BLACK_HEAVEN_MIN_BATTLE_BUBBLES = 3
    BLACK_HEAVEN_BUBBLE_OUTCOME_WEIGHT = {"nothing": 25, "ascension_pill": 20, "essence_crystal": 15, "essence_pill": 15, "materials": 20, "immortal_notes": 5}
    BLACK_HEAVEN_ESSENCE_CRYSTAL_QUANTITY_RANGE = (40, 150)
    BLACK_HEAVEN_ESSENCE_PILL_MIN_TIER = 5
    BLACK_HEAVEN_ESSENCE_PILL_MAX_TIER = 7

    def generate_black_heaven_board(self, team_size: int) -> list:
        """Returns BLACK_HEAVEN_BOARD_SIZE (20) bubble labels: BLACK_HEAVEN_MIN_BATTLE_BUBBLES
        (3) guaranteed "battle", exactly ONE guaranteed "gu" (unpredictable position), and the
        rest independently rolled via BLACK_HEAVEN_BUBBLE_OUTCOME_WEIGHT -- direct mirror of
        generate_inheritance_ground_board's own shape."""
        size = self.BLACK_HEAVEN_BOARD_SIZE
        outcomes = list(self.BLACK_HEAVEN_BUBBLE_OUTCOME_WEIGHT.keys())
        weights = list(self.BLACK_HEAVEN_BUBBLE_OUTCOME_WEIGHT.values())
        filler_count = size - self.BLACK_HEAVEN_MIN_BATTLE_BUBBLES - 1  # -1 for the single guaranteed "gu" bubble
        board = ["battle"] * self.BLACK_HEAVEN_MIN_BATTLE_BUBBLES + ["gu"] + random.choices(outcomes, weights=weights, k=filler_count)
        random.shuffle(board)
        return board

    def max_black_heaven_pops(self, team_size: int) -> int:
        return team_size * self.BLACK_HEAVEN_BUBBLES_PER_TEAM_MEMBER

    def roll_black_heaven_bubble_gu(self) -> str:
        """The guaranteed "gu" bubble's own resolution (see generate_black_heaven_board) --
        unlike roll_black_heaven_battle_bonus_gu, this bubble already committed to the
        outcome, so no chance gate is needed, just which of the 15 names. Immortal quality
        (2026-08-14, explicit request, raised from the original Common) -- the whole team
        already has to roll off for it (see grant_black_heaven_gu_reward), so the one winner
        gets the top tier."""
        name = random.choice(canon_gu_black_heaven.BLACK_HEAVEN_CANON_GU_NAMES)
        return equipment.gu_item_name(name, "Immortal")

    def grant_black_heaven_gu_reward(self, team: list) -> dict:
        """The guaranteed "gu" bubble now awards ONE of Black Heaven's own 15 Gu to the whole
        team's own dice-roll-off winner, per explicit request ("when the gu is found have all
        characters roll for it and show what they rolled") -- direct mirror of Inheritance
        Ground's own Core Gu share resolution (see InheritanceGroundView's no-backstab branch,
        inheritance_ground_view.py): everyone rolls 1-100, highest wins, ties broken randomly.
        Only the winner actually receives the item. Returns a dict (not a per-member list, since
        there's now exactly one outcome to show, not one per person):
        {"rolls": [(name, roll), ...], "winner_name": str, "winner_roll": int, "gu_name": str,
        "gu_family": str, "effect_text": str}."""
        gu_name = self.roll_black_heaven_bubble_gu()
        gu_family, _quality = equipment.parse_gu_name(gu_name)
        rolls = [(uid, name, random.randint(1, 100)) for uid, name in team]
        best_roll = max(roll for _, _, roll in rolls)
        winner_id, winner_name, _ = random.choice([r for r in rolls if r[2] == best_roll])
        self.db.add_item(winner_id, gu_name, 1)
        canon = canon_gu.CANON_GU_BY_NAME.get(gu_family, {})
        return {
            "rolls": [(name, roll) for _, name, roll in rolls],
            "winner_name": winner_name, "winner_roll": best_roll,
            "gu_name": gu_name, "gu_family": gu_family,
            "effect_text": canon.get("effect_text", ""),
        }

    def grant_black_heaven_pill_reward(self, team: list) -> list:
        """An "ascension_pill" bubble (2026-08-14, see BLACK_HEAVEN_BUBBLE_OUTCOME_WEIGHT) --
        direct mirror of grant_inheritance_ground_pill_reward's own shape: guaranteed grant,
        tier randomized via the same shared items.QI_ASCENSION_PILL_TIER_WEIGHTS (now covering
        1-8), one independent roll per team member. Returns [(name, reward_str), ...]."""
        tiers = list(items.QI_ASCENSION_PILL_TIER_WEIGHTS.keys())
        weights = list(items.QI_ASCENSION_PILL_TIER_WEIGHTS.values())
        results = []
        for user_id, name in team:
            tier = random.choices(tiers, weights=weights, k=1)[0]
            pill_name = items.alchemy_pill_name("Qi Ascension", tier)
            self.db.add_item(user_id, pill_name, 1)
            results.append((name, f"1x **{pill_name}**"))
        return results

    def grant_black_heaven_essence_crystal_reward(self, team: list) -> list:
        results = []
        for user_id, name in team:
            qty = random.randint(*self.BLACK_HEAVEN_ESSENCE_CRYSTAL_QUANTITY_RANGE)
            self.db.add_item(user_id, "Primeval Essence Crystal", qty)
            results.append((name, f"{qty}x **Primeval Essence Crystal**"))
        return results

    def grant_black_heaven_essence_pill_reward(self, team: list) -> list:
        sub_weights = {
            t: w for t, w in items.ESSENCE_RESTORATION_PILL_TIER_WEIGHTS.items()
            if self.BLACK_HEAVEN_ESSENCE_PILL_MIN_TIER <= t <= self.BLACK_HEAVEN_ESSENCE_PILL_MAX_TIER
        }
        tiers = list(sub_weights.keys())
        weights = list(sub_weights.values())
        results = []
        for user_id, name in team:
            tier = random.choices(tiers, weights=weights, k=1)[0]
            pill_name = items.alchemy_pill_name("Essence Restoration", tier)
            self.db.add_item(user_id, pill_name, 1)
            results.append((name, f"1x **{pill_name}**"))
        return results

    def grant_black_heaven_material_reward(self, team: list) -> list:
        """A "materials" bubble (see generate_black_heaven_board) -- rolls each of the existing
        generic Tier 8 items independently per team member (mirrors content/monsters/white_
        heaven.py's own multi-roll drop shape), no new named items. A guaranteed-minimum
        fallback (Tier 8 Ore if every independent roll happens to miss) keeps this bubble from
        ever reading identically to "nothing". Tier 8 Herb added 2026-08-14 -- previously the
        one generic Tier 8 item this bubble's own docstring claimed to grant but didn't."""
        results = []
        for user_id, name in team:
            granted = {}
            if random.random() < 0.55:
                granted["Tier 8 Ore"] = random.randint(3, 8)
            if random.random() < 0.55:
                granted["Tier 8 Beast Material"] = random.randint(2, 6)
            if random.random() < 0.35:
                granted["Tier 8 Beast Core"] = random.randint(1, 3)
            if random.random() < 0.45:
                granted["Tier 8 Herb"] = random.randint(2, 5)
            if not granted:
                granted["Tier 8 Ore"] = random.randint(3, 8)
            for item_name, qty in granted.items():
                self.db.add_item(user_id, item_name, qty)
            parts = [f"{qty}x {item_name}" for item_name, qty in granted.items()]
            results.append((name, ", ".join(parts)))
        return results

    def grant_black_heaven_immortal_notes_reward(self, team: list) -> list:
        """An "immortal_notes" bubble (2026-08-14, see generate_black_heaven_board) --
        direct mirror of grant_inheritance_ground_immortal_notes_reward's own shape:
        guaranteed 1x Immortal Notes per team member. Returns [(name, reward_str), ...]."""
        results = []
        for user_id, name in team:
            self.db.add_item(user_id, "Immortal Notes", 1)
            results.append((name, "1x **Immortal Notes**"))
        return results

    # -- Gathering: /mine, /gather, /explore -----------------------------------
    # All three share a 15-minute cooldown (tracked independently per action) and let Luck
    # (base stat + equipment bonuses) nudge the tier/rarity roll toward better results.

    MINE_COOLDOWN_SECONDS = 900
    GATHER_COOLDOWN_SECONDS = 900
    EXPLORE_COOLDOWN_SECONDS = 900
    PVP_COOLDOWN_SECONDS = 1800
    REST_COOLDOWN_SECONDS = 1800
    MEDITATE_COOLDOWN_SECONDS = 1800
    BATTLEFIELD_COOLDOWN_SECONDS = 6 * 3600

    def _effective_luck(self, user_id: int, player) -> int:
        return player["luck_stat"] + self.compute_equipment_bonuses(user_id)["stats"]["luck_stat"]

    def _trait_bonus(self, player, key: str) -> float:
        """A named root's AND a named physique's own stat_bonuses value for `key` (see
        character_data.CharacterTraitSpec), PLUS the equipped Gu's own stat_bonuses value for
        it (see world_boss.py's Divine Concealment/Dream Wings/Heavenly Secret/Divine Travel
        Gu — the first World Boss Gu to grant one of these root/physique-only-until-now keys)
        — 0 from any side that doesn't have one or doesn't touch this key. Used by every hook
        below that isn't already covered by compute_equipment_bonuses' own root/physique
        fold-in (gather/mine/farm yield, healing items, meditate, breakthrough Qi loss,
        explore luck, gear dismantle — all read straight off `player`/a cooldown check rather
        than combat stats, so they look the bonus up here instead of going through the
        combat-stat pipeline)."""
        root_spec = chargen.get_root_spec(player["root_name"])
        physique_spec = chargen.get_physique_spec(player["physique_name"])
        total = (root_spec.stat_bonuses.get(key, 0) if root_spec else 0) + (physique_spec.stat_bonuses.get(key, 0) if physique_spec else 0)
        gu_item_name = self.db.get_equipped(player["user_id"]).get("gu_ability")
        gu = equipment.EQUIPMENT.get(gu_item_name) if gu_item_name else None
        if gu:
            total += gu.stat_bonuses.get(key, 0)
        return total

    def _gu_pet_cultivation_bonus(self, player, key: str) -> float:
        """An active MATURE Gu Pet's own Cultivation-Mode specialty contribution to `key`
        (see gu_pet.roll_specialty_bonus -- gear_budget_bonus_pct/manual_rarity_bonus_pct are
        the only two keys this ever actually finds today), satiety-scaled. Kept separate from
        _trait_bonus (root/physique/Gu ability, all pure dict lookups) rather than folded into
        it, since this needs a real DB read (+ lazy satiety-settlement write, see get_gu_pet)
        that would add unnecessary DB traffic to every OTHER _trait_bonus call site (mining,
        gathering, meditate, study, ...) that has nothing to do with Gu Pets."""
        if not player["active_gu_pet_id"]:
            return 0.0
        pet = self.get_gu_pet(player["active_gu_pet_id"])
        if pet is None or pet["stage"] != gu_pet.STAGE_MATURE or pet["mode"] != gu_pet.MODE_CULTIVATION:
            return 0.0
        satiety_mult, _ = gu_pet.satiety_band(pet["satiety"])
        return pet["stat_bonuses"].get(key, 0) * satiety_mult

    def _check_cooldown(self, player, column: str, cooldown_seconds: int, extra_reduction_pct: float = 0.0):
        """Returns remaining seconds (0 if ready). A manual's cooldown_reduction_pct (see
        manual_view.EFFECT_LABELS) — and the Time Dao Path's own scaled bonus, folded into the
        same generic key by compute_equipment_bonuses — shortens every cooldown gated through
        here — mine, gather, explore, pvp, rest, meditate, and manual swaps alike. extra_
        reduction_pct stacks on top for a caller-specific bonus (only meditate() passes one
        today, for Wisdom's meditate_cooldown_reduction_pct, deliberately kept separate from
        the generic key so the two paths' bonuses add rather than one overwriting the other).
        Combined reduction is floored so a cooldown can never fully zero out."""
        reduction = self.compute_equipment_bonuses(player["user_id"]).get("cooldown_reduction_pct", 0) + extra_reduction_pct
        effective_seconds = round(cooldown_seconds * (1 - min(0.9, max(0.0, reduction))))
        return max(0, effective_seconds - (int(time.time()) - player[column]))

    def get_cooldowns_status(self, user_id: int, name: str) -> dict:
        """Read-only — remaining seconds (0 if ready) for /mine, /gather, /explore, /rest,
        /meditate, /teach, /battlefield, /tournament, /search_forgotten_blessed_land,
        /inheritance_ground, for /cd."""
        player = self.db.get_or_create_player(user_id, name)
        tournament_phase, tournament_row = self.get_tournament_status()
        companion = self.db.get_dao_companion(user_id)
        return {
            "player": player,
            "mine_remaining": self._check_cooldown(player, "last_mine_ts", self.MINE_COOLDOWN_SECONDS),
            "gather_remaining": self._check_cooldown(player, "last_gather_ts", self.GATHER_COOLDOWN_SECONDS),
            "explore_remaining": self._check_cooldown(player, "last_explore_ts", self.EXPLORE_COOLDOWN_SECONDS),
            "pvp_remaining": self._check_cooldown(player, "last_pvp_ts", self.PVP_COOLDOWN_SECONDS),
            "rest_remaining": self._check_cooldown(player, "last_rest_ts", self.REST_COOLDOWN_SECONDS),
            "meditate_remaining": self._check_cooldown(player, "last_meditate_ts", self.MEDITATE_COOLDOWN_SECONDS),
            "battlefield_remaining": self._check_cooldown(player, "last_battlefield_ts", self.BATTLEFIELD_COOLDOWN_SECONDS),
            "world_boss_remaining": self._check_cooldown(player, "last_world_boss_attack_ts", world_boss.WORLD_BOSS_ATTACK_COOLDOWN_SECONDS),
            "inheritance_ground_remaining": self.inheritance_ground_cooldown_remaining(player),
            # Search Black Heaven -- only meaningful once realm-eligible (see black_heaven.
            # is_eligible), same "only show gated features once relevant" convention as
            # treasure_hunt_eligible just below.
            "black_heaven_search_eligible": black_heaven.is_eligible(realms.STAGES[player["realm_index"]].great_realm_index),
            "black_heaven_search_remaining": self.black_heaven_search_cooldown_remaining(player),
            # /search_forgotten_blessed_land -- only meaningful once realm-eligible (see
            # start_treasure_hunt's own gate), same "only show gated features once relevant"
            # convention as has_dao_companion/sect_disciple_count/personal_disciple_count below.
            "treasure_hunt_eligible": realms.STAGES[player["realm_index"]].great_realm_index >= self.TREASURE_HUNT_REALM_GATE,
            "treasure_hunt_remaining": self._check_cooldown(player, "treasure_hunt_last_ts", self.TREASURE_HUNT_COOLDOWN_SECONDS),
            # Only meaningful with an active Dao Companion -- /cd only shows these lines when
            # has_dao_companion is true (see dao_companion_burst / /companion's Daily Burst
            # button, and essence_exchange_propose / /essence_exchange). The Essence Exchange cooldown
            # lives on the dao_companions row itself (last_essence_exchange_ts, PER PAIR, not
            # per player -- see project_essence_exchange), so it can't go through
            # _check_cooldown (which reads a column off the player row); computed the same
            # way essence_exchange_propose itself does.
            "has_dao_companion": companion is not None,
            "dc_burst_remaining": self._check_cooldown(player, "last_dc_burst_ts", dao_companion.DAO_COMPANION_BURST_COOLDOWN_SECONDS),
            "essence_exchange_remaining": (
                max(0, self.ESSENCE_EXCHANGE_COOLDOWN_SECONDS - (int(time.time()) - companion["last_essence_exchange_ts"]))
                if companion is not None else 0
            ),
            # Tournament isn't a per-player last_x_ts cooldown -- it's the shared global
            # signup/cooldown cycle from GameManager.get_tournament_status (same source of
            # truth TournamentView itself renders from), so /cd shows phase + row instead of a
            # single remaining-seconds number.
            "tournament_phase": tournament_phase,
            "tournament_row": tournament_row,
            # Only meaningful once there's actually a disciple roster to teach — /cd only
            # shows these lines when sect_disciple_count/personal_disciple_count > 0.
            "sect_disciple_count": self.db.count_disciples(user_id),
            "teach_remaining": self._check_cooldown(player, "last_teach_ts", sects.TEACH_COOLDOWN_SECONDS),
            "personal_disciple_count": self.db.count_personal_disciples(user_id),
            # Per-disciple cooldowns (see personal_teach_all) mean there's no single number
            # for "the" personal teach cooldown anymore — /cd shows a ready/on-cooldown
            # breakdown instead, see _personal_teach_readiness.
            "personal_teach_readiness": self._personal_teach_readiness(user_id),
            # /view_servant's Dual Cultivate -- only meaningful once BOTH Combat and Support
            # slots are filled (same "only show gated features once relevant" convention as
            # has_dao_companion above).
            "dual_cultivate_eligible": self.combined_servant_power(user_id) is not None,
            "dual_cultivate_remaining": self._check_cooldown(player, "last_dual_cultivate_ts", self.DUAL_CULTIVATE_COOLDOWN_SECONDS),
        }

    def _personal_teach_readiness(self, master_id: int) -> dict:
        """How many of a personal master's disciples are ready to teach right now vs still
        on their own cooldown (see personal_teach_all), plus the soonest any of the latter
        become ready — for /cd's summary line."""
        disciples = self.db.get_personal_disciples(master_id)
        if not disciples:
            return {"ready": 0, "on_cooldown": 0, "soonest_remaining": 0}
        reduction = self.compute_equipment_bonuses(master_id).get("cooldown_reduction_pct", 0)
        effective_cooldown = round(sects.PERSONAL_TEACH_COOLDOWN_SECONDS * (1 - min(0.9, max(0.0, reduction))))
        now = int(time.time())
        ready = 0
        remainings = []
        for row in disciples:
            remaining = max(0, effective_cooldown - (now - row["personal_last_taught_ts"]))
            if remaining <= 0:
                ready += 1
            else:
                remainings.append(remaining)
        return {"ready": ready, "on_cooldown": len(remainings), "soonest_remaining": min(remainings) if remainings else 0}

    # -- Rest & Meditate: /rest, /meditate ----------------------------------------------
    # Simple no-frills recovery actions — unlike /mine, /gather, /explore they resolve
    # instantly (no multi-node View session) since there's nothing to reveal one step at a
    # time. Tunable reward sizes.
    REST_HEAL_PERCENT = 0.20
    REST_STONES_MIN = 15
    REST_STONES_MAX = 40

    MEDITATE_HEAL_PERCENT = 0.10
    MEDITATE_ESSENCE_PERCENT = 0.10
    # "A bit of qi" is scaled off the player's own passive rate rather than a flat number,
    # so it stays meaningful at every realm instead of being trivial at high aptitude/late
    # game and disproportionate at low aptitude/early game.
    MEDITATE_QI_MINUTES_EQUIVALENT = 15

    def rest(self, user_id: int, name: str) -> dict:
        """Returns {"ok": False, "remaining_seconds": ...} or {"ok": True, "healed", "hp",
        "max_hp", "stones"}."""
        player = self.db.get_or_create_player(user_id, name)
        remaining = self._check_cooldown(player, "last_rest_ts", self.REST_COOLDOWN_SECONDS)
        if remaining > 0:
            return {"ok": False, "remaining_seconds": remaining}
        healed, hp, max_hp = self.db.heal_percent(user_id, self.REST_HEAL_PERCENT)
        stones = random.randint(self.REST_STONES_MIN, self.REST_STONES_MAX)
        self.db.add_spirit_stones(user_id, stones)
        self.db.set_timestamp_column(user_id, "last_rest_ts", int(time.time()))
        return {"ok": True, "healed": healed, "hp": hp, "max_hp": max_hp, "stones": stones}

    def meditate(self, user_id: int, name: str) -> dict:
        """Returns {"ok": False, "remaining_seconds": ...} or {"ok": True, "healed", "hp",
        "max_hp", "essence_restored", "essence", "max_essence", "qi_gained", "qi"}."""
        player = self.db.get_or_create_player(user_id, name)
        wisdom_cooldown_reduction = self.get_dao_path_totals(user_id).get("meditate_cooldown_reduction_pct", 0)
        remaining = self._check_cooldown(player, "last_meditate_ts", self.MEDITATE_COOLDOWN_SECONDS, extra_reduction_pct=wisdom_cooldown_reduction)
        if remaining > 0:
            return {"ok": False, "remaining_seconds": remaining}
        healed, hp, max_hp = self.db.heal_percent(user_id, self.MEDITATE_HEAL_PERCENT)
        bonuses = self.compute_equipment_bonuses(user_id)
        essence_percent = self.MEDITATE_ESSENCE_PERCENT * (1 + bonuses.get("meditate_essence_bonus_pct", 0))
        essence_restored, essence, max_essence = self.db.restore_essence_percent(user_id, essence_percent)
        effective_rate = self.db.get_qi_status(user_id)["effective_rate_per_minute"]
        qi_gained = effective_rate * self.MEDITATE_QI_MINUTES_EQUIVALENT * (1 + self._trait_bonus(player, "meditate_qi_pct"))
        new_qi = self.db.add_qi(user_id, qi_gained)
        # A Lightning-family root's own "/meditate restores battle Qi" mechanic — battle Qi
        # otherwise only regenerates passively over real time (see settle_battle_qi), so this
        # is meditate's one direct top-up of it.
        battle_qi_bonus_pct = self._trait_bonus(player, "meditate_battle_qi_pct")
        if battle_qi_bonus_pct > 0:
            settled = self.db.settle_battle_qi(user_id)
            self.db.set_battle_qi(user_id, min(settled["qi_stat"], settled["battle_qi"] + settled["qi_stat"] * battle_qi_bonus_pct))
        self.db.set_timestamp_column(user_id, "last_meditate_ts", int(time.time()))
        return {
            "ok": True, "healed": healed, "hp": hp, "max_hp": max_hp,
            "essence_restored": essence_restored, "essence": essence, "max_essence": max_essence,
            "qi_gained": qi_gained, "qi": new_qi,
        }

    MINE_VEIN_NODE_COUNT = 5

    def start_mining_vein(self, user_id: int, name: str) -> dict:
        """/mine now opens a vein of MINE_VEIN_NODE_COUNT nodes (see MiningVeinView) instead
        of granting ore directly — the cooldown is spent here, once, for the whole vein, not
        per node. Returns {"ok": False, "remaining_seconds": ...} or {"ok": True, "nodes": [...]}
        where each node is {"item_name", "tier", "quantity"} pre-rolled with this roll's Luck/
        Miner-rank bonuses already applied."""
        player = self.db.get_or_create_player(user_id, name)
        remaining = self._check_cooldown(player, "last_mine_ts", self.MINE_COOLDOWN_SECONDS)
        if remaining > 0:
            return {"ok": False, "remaining_seconds": remaining}
        effective_luck = self._effective_luck(user_id, player)
        yield_mult = (
            professions.yield_multiplier(player["miner_rank"])
            * self._region_bonus_dict(player).get("gather_yield_multiplier", 1.0)
            * (1 + self._trait_bonus(player, "mining_yield_pct") + self._grotto_yield_bonus(player) + self._servant_yield_bonus(user_id, "mining_yield_pct"))
        )
        nodes = []
        for _ in range(self.MINE_VEIN_NODE_COUNT):
            tier = gathering.roll_tier(effective_luck)
            quantity = gathering.roll_quantity(yield_mult)
            nodes.append({"item_name": f"Tier {tier} Ore", "tier": tier, "quantity": quantity})
        self.db.set_timestamp_column(user_id, "last_mine_ts", int(time.time()))
        return {"ok": True, "nodes": nodes, "region_find": self.maybe_trigger_region_discovery(user_id, name)}

    def collect_mining_vein(self, user_id: int, collected: dict):
        """Grants whatever a MiningVeinView session actually struck (collected is
        {item_name: quantity}) — called once when the vein ends, whether by finishing all
        nodes or leaving early."""
        for item_name, quantity in collected.items():
            self.db.add_item(user_id, item_name, quantity)

    GATHER_PATCH_NODE_COUNT = 5

    def start_gathering_patch(self, user_id: int, name: str) -> dict:
        """/gather works just like /mine (see start_mining_vein) — a patch of
        GATHER_PATCH_NODE_COUNT herb nodes, pre-rolled with this roll's Luck/Gatherer-rank
        bonuses, foraged one at a time via GatheringPatchView. The cooldown is spent once for
        the whole patch, not per node. Returns {"ok": False, "remaining_seconds": ...} or
        {"ok": True, "nodes": [...]} where each node is {"item_name", "tier", "quantity"}."""
        player = self.db.get_or_create_player(user_id, name)
        remaining = self._check_cooldown(player, "last_gather_ts", self.GATHER_COOLDOWN_SECONDS)
        if remaining > 0:
            return {"ok": False, "remaining_seconds": remaining}
        effective_luck = self._effective_luck(user_id, player)
        yield_mult = (
            professions.yield_multiplier(player["gatherer_rank"])
            * self._region_bonus_dict(player).get("gather_yield_multiplier", 1.0)
            * (1 + self._trait_bonus(player, "herb_yield_pct") + self._grotto_yield_bonus(player) + self._servant_yield_bonus(user_id, "herb_yield_pct"))
        )
        nodes = []
        for _ in range(self.GATHER_PATCH_NODE_COUNT):
            tier = gathering.roll_tier(effective_luck)
            quantity = gathering.roll_quantity(yield_mult)
            nodes.append({"item_name": f"Tier {tier} Herb", "tier": tier, "quantity": quantity})
        self.db.set_timestamp_column(user_id, "last_gather_ts", int(time.time()))
        return {"ok": True, "nodes": nodes, "region_find": self.maybe_trigger_region_discovery(user_id, name)}

    def collect_gathering_patch(self, user_id: int, collected: dict):
        """Grants whatever a GatheringPatchView session actually foraged — called once when
        the patch ends, whether by finishing all nodes or leaving early."""
        for item_name, quantity in collected.items():
            self.db.add_item(user_id, item_name, quantity)

    EXPLORE_HUNT_NODE_COUNT = 5

    # Rogue path's "higher chance to encounter hidden inheritances, secret realms, rare
    # merchants, lucky events, and ancient ruins" — folded in as extra effective luck, but
    # only for /explore specifically (not /mine or /gather too, which _effective_luck is
    # also shared by), matching what the passive actually describes.
    ROGUE_EXPLORE_LUCK_BONUS = 15

    def start_exploration_hunt(self, user_id: int, name: str) -> dict:
        """/explore works just like /mine and /gather (see start_mining_vein) — a trail of
        EXPLORE_HUNT_NODE_COUNT finds, pre-rolled with this roll's Luck/Explorer-rank bonuses,
        hunted down one at a time via ExplorationHuntView. The cooldown is spent once for the
        whole trail, not per find. Returns {"ok": False, "remaining_seconds": ...} or
        {"ok": True, "nodes": [...], "white_heaven": bool} where each node is {"band",
        "stones", "item_name", "quantity", "page_id", "page_quantity"} (see exploration.
        roll_explore — exactly one of stones/item_name/page_id is set). white_heaven mirrors
        whether the caller's own White Heaven status was "present" for this roll (see
        ExplorationHuntView) -- for its own reward-pool swap, not just display."""
        player = self.db.get_or_create_player(user_id, name)
        remaining = self._check_cooldown(player, "last_explore_ts", self.EXPLORE_COOLDOWN_SECONDS)
        if remaining > 0:
            return {"ok": False, "remaining_seconds": remaining}
        effective_luck = self._effective_luck(user_id, player)
        if player["cultivation_path"] == "Rogue":
            effective_luck += self.ROGUE_EXPLORE_LUCK_BONUS
        # A Wind-family root's "+X% /explore rarity weighting" (see
        # character_data.CharacterTraitSpec) — folded in as extra effective luck, the same
        # trick Rogue's own path passive already uses just above.
        effective_luck += self._trait_bonus(player, "explore_luck_bonus_flat")
        in_white_heaven = player["white_heaven_status"] == "present"
        nodes = [exploration.roll_explore(player["explorer_rank"], effective_luck, white_heaven=in_white_heaven) for _ in range(self.EXPLORE_HUNT_NODE_COUNT)]
        stone_mult = self._region_bonus_dict(player).get("explore_stone_multiplier", 1.0)
        if stone_mult != 1.0:
            for node in nodes:
                if node["stones"]:
                    node["stones"] = round(node["stones"] * stone_mult)
        self.db.set_timestamp_column(user_id, "last_explore_ts", int(time.time()))
        return {"ok": True, "nodes": nodes, "white_heaven": in_white_heaven, "region_find": self.maybe_trigger_region_discovery(user_id, name)}

    def collect_exploration_hunt(self, user_id: int, collected_stones: int, collected_items: dict, collected_pages: dict = None):
        """Grants whatever an ExplorationHuntView session actually hunted down — called once
        when the trail ends, whether by finishing all finds or leaving early. collected_pages
        is {page_id: quantity} -- pages live in their own player_pages table (see
        GameDatabase.add_player_page), not the generic inventory collected_items grants
        through, so they need their own grant call."""
        if collected_stones:
            self.db.add_spirit_stones(user_id, collected_stones)
        for item_name, quantity in collected_items.items():
            self.db.add_item(user_id, item_name, quantity)
        for page_id, quantity in (collected_pages or {}).items():
            self.db.add_player_page(user_id, page_id, quantity)
        self.grant_dao_marks(user_id)

    # -- PvP: /pvp ---------------------------------------------------------------
    # "Searches for other players using the pvp command" — anyone else whose last_pvp_ts is
    # within PVP_COOLDOWN_SECONDS is, by definition, someone who recently ran /pvp themselves,
    # so that pool doubles as a lightweight matchmaking queue with no separate table needed.
    # If nobody qualifies, falls back to a uniformly random other confirmed character. Either
    # way the "opponent" is a one-time stat snapshot (at full HP, so a target who happens to
    # be badly hurt right now isn't an unfair freebie) — never a live second player, and never
    # anything written back to their account; only the initiator's own outcome is real.

    PVP_STONE_MIN = 15
    PVP_STONE_MAX = 40

    def find_pvp_opponent(self, user_id: int):
        """Returns (opponent_player_row, is_real_recent_searcher) or (None, False) if this
        player is the only confirmed character that exists yet."""
        cutoff = int(time.time()) - self.PVP_COOLDOWN_SECONDS
        recent = self.db.get_recent_pvp_players(user_id, cutoff)
        if recent:
            return random.choice(recent), True
        everyone = self.db.get_confirmed_players(user_id)
        if everyone:
            return random.choice(everyone), False
        return None, False

    def opponent_combat_snapshot(self, opponent_player) -> dict:
        """A one-time-computed stat block for the PvP opponent side — folds in their equipped
        gear's flat combat-stat bonuses (so a well-geared clone actually fights like one),
        including HP (see hunt.py/raid.py's hp_bonus handling — same idea, just simpler here
        since the opponent's HP is a one-shot snapshot with nothing to persist back). Runtime
        "special" bonuses (lifesteal, crit, dodge, ...) are skipped to keep the AI opponent
        simple and self-contained. Their class's foundation-stat bonuses (Tank's +HP/+DEF,
        etc.) don't need separate handling — those are already baked into hp/def_stat at
        confirm time, same as everyone else's."""
        bonuses = self.compute_equipment_bonuses(opponent_player["user_id"])
        stats_bonus = bonuses["stats"]
        return {
            "atk_stat": opponent_player["atk_stat"] + stats_bonus["atk_stat"],
            "str_stat": opponent_player["str_stat"] + stats_bonus["str_stat"],
            "def_stat": opponent_player["def_stat"] + stats_bonus["def_stat"],
            "spd_stat": opponent_player["spd_stat"] + stats_bonus["spd_stat"],
            "luck_stat": opponent_player["luck_stat"] + stats_bonus["luck_stat"],
            "hp": opponent_player["max_hp"] + stats_bonus["hp"],
        }

    def start_pvp(self, user_id: int, name: str) -> dict:
        player = self.db.get_or_create_player(user_id, name)
        remaining = self._check_cooldown(player, "last_pvp_ts", self.PVP_COOLDOWN_SECONDS)
        if remaining > 0:
            return {"ok": False, "remaining_seconds": remaining}
        opponent_player, is_real = self.find_pvp_opponent(user_id)
        if opponent_player is None:
            return {"ok": False, "reason": "no_opponents"}
        self.db.set_timestamp_column(user_id, "last_pvp_ts", int(time.time()))
        return {
            "ok": True,
            "opponent_name": opponent_player["character_name"] or "a wandering cultivator",
            "opponent_stats": self.opponent_combat_snapshot(opponent_player),
            "is_real": is_real,
        }

    def award_pvp_victory(self, user_id: int) -> int:
        stones = random.randint(self.PVP_STONE_MIN, self.PVP_STONE_MAX)
        self.db.add_spirit_stones(user_id, stones)
        return stones

    # -- Leaderboard: /leaderboard -------------------------------------------------
    # "Combat power" isn't used anywhere else — it's a leaderboard-only composite score,
    # not a real combat formula. STR/ATK/DEF/SPD (combat.py's four core stats) count at full
    # weight; Luck at half (it's more of a bonus stat than a core one); HP/QI at a tenth,
    # since they're naturally 5-10x larger numbers than the others and would otherwise drown
    # everything else out. Equipped gear/class/buffs are folded in via
    # compute_equipment_bonuses, so it reflects effective power, not just base stats.
    LEADERBOARD_TOP_N = 15
    COMBAT_POWER_WEIGHTS = {
        "str_stat": 1.0, "atk_stat": 1.0, "def_stat": 1.0, "spd_stat": 1.0,
        "luck_stat": 0.5, "hp": 0.1, "qi_stat": 0.1,
    }

    def compute_combat_power(self, player) -> int:
        stats_bonus = self.compute_equipment_bonuses(player["user_id"])["stats"]
        total = sum((player[stat] + stats_bonus.get(stat, 0)) * weight for stat, weight in self.COMBAT_POWER_WEIGHTS.items())
        return round(total)

    def get_leaderboard(self, top_n: int = None) -> dict:
        """{"by_realm": [...], "by_stones": [...], "by_power": [...], "by_speed": [...],
        "by_boss_damage": [...], "boss_damage_context": {...}} — each *_by list is up to top_n
        entries, sorted highest-first for that category. qi_rate is the same effective
        qi/minute figure /qi reports — aptitude, permanent qi_multiplier, active buffs, and
        race/root/physique/path bonuses all folded in, so it's real "how fast do you actually
        cultivate" rather than just the flat cultivation_speed_pct stat_bonus in isolation.
        by_boss_damage is scoped to the CURRENTLY active World Boss instance (see
        world_boss_damage's own table comment) -- it naturally "resets" on every new spawn
        since a fresh boss_instance_id starts with zero contributor rows, no separate reset
        step needed; boss_damage_context carries the active boss's name/HP (or active=False)
        for the view to show alongside it."""
        top_n = top_n or self.LEADERBOARD_TOP_N
        entries = [
            {
                "user_id": player["user_id"],
                "name": player["character_name"] or player["name"],
                "realm_index": player["realm_index"],
                "spirit_stones": player["spirit_stones"],
                "combat_power": self.compute_combat_power(player),
                "qi_rate": self.db.get_qi_status(player["user_id"])["effective_rate_per_minute"],
            }
            for player in self.db.get_all_confirmed_players()
        ]

        active_boss = self.db.get_active_world_boss()
        if active_boss:
            contributors = self.db.get_world_boss_contributors(active_boss["boss_instance_id"])[:top_n]
            boss_damage_entries = [
                {"user_id": c["user_id"], "name": c["name"], "damage_dealt": c["damage_dealt"], "attacks": c["attacks"]}
                for c in contributors
            ]
            roster = world_boss.WORLD_BOSSES[active_boss["boss_key"]]
            boss_damage_context = {
                "active": True, "boss_name": roster["name"], "boss_emoji": roster["emoji"],
                "current_hp": active_boss["current_hp"], "max_hp": active_boss["max_hp"],
            }
        else:
            boss_damage_entries = []
            boss_damage_context = {"active": False}

        return {
            "by_realm": sorted(entries, key=lambda e: e["realm_index"], reverse=True)[:top_n],
            "by_stones": sorted(entries, key=lambda e: e["spirit_stones"], reverse=True)[:top_n],
            "by_power": sorted(entries, key=lambda e: e["combat_power"], reverse=True)[:top_n],
            "by_speed": sorted(entries, key=lambda e: e["qi_rate"], reverse=True)[:top_n],
            "by_boss_damage": boss_damage_entries,
            "boss_damage_context": boss_damage_context,
        }

    # -- Farming: /farm ---------------------------------------------------------

    # Deliberately stops at 7 -- /farm tops out one tier below blacksmith.MAX_TIER/alchemy.
    # MAX_TIER's own Tier 8 (explore/sfbl/Inheritance Ground/Search Black Heaven only, per
    # explicit request that Tier 8 Herb NOT be farmable). farm_view.py's own tier Select
    # already only ever offers range(1, 8), so this was never reachable through the UI, but
    # plant_farm/plant_all_farm below now refuse it explicitly too rather than relying on
    # that alone -- a bare `HERB_GROWTH_HOURS[tier]` KeyError for tier 8 would otherwise be a
    # confusing crash instead of a clean refusal if this ever got called some other way.
    HERB_GROWTH_HOURS = {1: 0.5, 2: 1, 3: 2, 4: 4, 5: 8, 6: 16, 7: 24}
    FARM_BASE_YIELD_RANGE = (3, 6)

    # Plot count scales with realm — 1 base slot, +2 more per Great Realm crossed (so a
    # fresh Qi Condensation character has 1 slot, a Foundation Establishment one has 3, and
    # so on up to 13 at Ancient Realm — the same Great Realm index hunt/raid/etc. use).
    FARM_BASE_SLOTS = 1
    FARM_SLOTS_PER_GREAT_REALM = 2

    def farm_slot_count(self, player) -> int:
        great_realm_index = realms.STAGES[player["realm_index"]].great_realm_index
        return self.FARM_BASE_SLOTS + self.FARM_SLOTS_PER_GREAT_REALM * great_realm_index

    def get_farm_overview(self, user_id: int, name: str) -> dict:
        """{"player", "max_slots", "slots": [{"slot_index", "state", ...}, ...]} — one entry
        per currently-unlocked slot, in order. state is "empty", "growing", or "ready"."""
        player = self.db.get_or_create_player(user_id, name)
        max_slots = self.farm_slot_count(player)
        plots = self.db.get_farm_plots(user_id)
        slots = []
        for slot_index in range(max_slots):
            plot = plots.get(slot_index)
            if plot is None:
                slots.append({"slot_index": slot_index, "state": "empty"})
                continue
            tier = plot["tier"]
            grow_hours = self.HERB_GROWTH_HOURS[tier]
            elapsed_hours = (time.time() - plot["planted_ts"]) / 3600
            state = "ready" if elapsed_hours >= grow_hours else "growing"
            slots.append({
                "slot_index": slot_index, "state": state, "tier": tier,
                "grow_hours": grow_hours, "elapsed_hours": elapsed_hours,
            })
        return {"player": player, "max_slots": max_slots, "slots": slots}

    def plant_farm(self, user_id: int, name: str, slot_index: int, tier: int):
        player = self.db.get_or_create_player(user_id, name)
        if tier not in self.HERB_GROWTH_HOURS:
            return False, "Tier 8 Herb can't be farmed — /farm tops out at Tier 7. Explore, /sfbl, and other endgame sources are the only way to get it."
        if slot_index < 0 or slot_index >= self.farm_slot_count(player):
            return False, "That plot slot isn't unlocked yet — reach a higher realm to gain more."
        if slot_index in self.db.get_farm_plots(user_id):
            return False, "That plot is already occupied."
        item_name = f"Tier {tier} Herb"
        if not self.db.remove_item(user_id, item_name, 1):
            return False, f"You don't have a **{item_name}** to plant."
        self.db.plant_farm_plot(user_id, slot_index, tier)
        return True, f"Planted a **{item_name}** in Plot {slot_index + 1} — ready in {self.HERB_GROWTH_HOURS[tier]:.1f} hours."

    def plant_all_farm(self, user_id: int, name: str, tier: int) -> dict:
        """Plants Tier `tier` Herb into every currently-EMPTY unlocked plot in one go — same
        per-plot mechanics as plant_farm (one herb consumed per slot, same Tier 8 refusal),
        just looped across every empty slot until either they're all filled or the player
        runs out of that tier's herb, whichever comes first. Returns {"planted": count,
        "item_name", "empty_slots": how many empty slots existed before this call}."""
        player = self.db.get_or_create_player(user_id, name)
        if tier not in self.HERB_GROWTH_HOURS:
            # Same refusal plant_farm gives, just shaped to match this method's own return
            # contract -- "planted": 0 already reads correctly through farm_view.py's own
            # existing "nothing to plant" fallback message with no caller changes needed.
            return {"planted": 0, "item_name": f"Tier {tier} Herb", "empty_slots": 0}
        max_slots = self.farm_slot_count(player)
        occupied = self.db.get_farm_plots(user_id)
        empty_slots = [i for i in range(max_slots) if i not in occupied]
        item_name = f"Tier {tier} Herb"
        planted = 0
        for slot_index in empty_slots:
            if not self.db.remove_item(user_id, item_name, 1):
                break
            self.db.plant_farm_plot(user_id, slot_index, tier)
            planted += 1
        return {"planted": planted, "item_name": item_name, "empty_slots": len(empty_slots)}

    def harvest_farm(self, user_id: int, name: str, slot_index: int):
        overview = self.get_farm_overview(user_id, name)
        slot = next((s for s in overview["slots"] if s["slot_index"] == slot_index), None)
        if slot is None or slot["state"] != "ready":
            return False, None, 0, "Nothing is ready to harvest yet."
        tier = slot["tier"]
        multiplier = professions.yield_multiplier(overview["player"]["farmer_rank"]) * (
            1 + self._trait_bonus(overview["player"], "herb_yield_pct") + self._grotto_yield_bonus(overview["player"])
            + self._servant_yield_bonus(user_id, "herb_yield_pct")
        )
        quantity = max(1, round(random.randint(*self.FARM_BASE_YIELD_RANGE) * multiplier))
        item_name = f"Tier {tier} Herb"
        self.db.add_item(user_id, item_name, quantity)
        self.db.clear_farm_plot_slot(user_id, slot_index)
        return True, item_name, quantity, None

    def harvest_all_farm(self, user_id: int, name: str) -> dict:
        """Harvests every currently-ready plot in one go — same per-plot yield roll and
        Farmer-rank multiplier as harvest_farm, just looped across every "ready" slot.
        Returns {"harvested": {item_name: quantity}, "plots_harvested": int}."""
        overview = self.get_farm_overview(user_id, name)
        harvested: dict = {}
        plots_harvested = 0
        for slot in overview["slots"]:
            if slot["state"] != "ready":
                continue
            ok, item_name, quantity, _ = self.harvest_farm(user_id, name, slot["slot_index"])
            if ok:
                harvested[item_name] = harvested.get(item_name, 0) + quantity
                plots_harvested += 1
        return {"harvested": harvested, "plots_harvested": plots_harvested}

    # -- Alchemy: /alchemy -------------------------------------------------------

    def _alchemy_salvage_bonus_pct(self, user_id: int, player=None) -> float:
        """Highest salvage_bonus pct among equipped accessories/artifacts (see
        accessories_data.py's "salvage_bonus" items, e.g. Nine-Embers Refinement Cauldron,
        Crimson Furnace Cauldron) OR a Refinement-family root's own craft_salvage_bonus_pct
        (see character_data.CharacterTraitSpec) — a chance for craft_pill/craft_gear to hand
        back one unit of a material it would otherwise consume. Not additive across sources;
        strongest one applies, same "one wins" convention as this codebase's search-cooldown
        accessories — a root and an accessory doing the same job shouldn't stack into
        something neither was individually balanced around."""
        best = 0.0
        for instance_id in self.db.get_equipped_accessory_ids(user_id).values():
            instance = self.db.get_accessory_instance(instance_id)
            affix = self._affix_for_instance(instance)
            if affix and affix.effect_key == "salvage_bonus":
                best = max(best, affix.effect_params.get("pct", 0.0))
        if player is not None:
            best = max(best, self._trait_bonus(player, "craft_salvage_bonus_pct"))
        return best

    # Genesis Lotus Inheritor Root's Karmic Divine Tree — successful crafts and newly-found
    # discoveries grow Karma (capped weekly), auto-converted to bonus Qi rather than needing
    # a separate weekly "harvest" command. [Simplified from the source brief's three separate
    # branches (cultivation/crafts/discoveries) with an explicit once-weekly harvest choice
    # between Qi/materials/Insight Dust: this tracks one combined pool auto-paid as Qi, and
    # "discoveries" specifically means finding one via /search, not fully resolving it —
    # tracking true resolution would mean hooking discovery_view.py/region_dream_realm_view.py/
    # battlefield_view.py's own separate completion flows too.]
    GENESIS_LOTUS_KARMA_PER_EVENT = 5
    GENESIS_LOTUS_KARMA_WEEKLY_CAP = 50

    def _maybe_grant_genesis_lotus_karma(self, player) -> int:
        """Returns bonus Qi actually granted (0 if this root isn't active or the weekly cap
        is already spent)."""
        root_spec = chargen.get_root_spec(player["root_name"])
        if not root_spec or root_spec.name != "Genesis Lotus Inheritor Root":
            return 0
        user_id = player["user_id"]
        before = self.db.peek_unique_weekly_resource(user_id)
        after = self.db.add_unique_weekly_resource(user_id, self.GENESIS_LOTUS_KARMA_PER_EVENT, self.GENESIS_LOTUS_KARMA_WEEKLY_CAP)
        gained = after - before
        if gained > 0:
            self.db.add_qi(user_id, gained)
        return gained

    def craft_pill(self, user_id: int, name: str, pill_type: str, tier: int) -> dict:
        """Consumes the recipe's herbs (+ any bonus ingredients) regardless of outcome (that's
        the crafting risk, unless a salvage_bonus item refunds one — see
        _alchemy_salvage_bonus_pct), then rolls success against the player's Alchemist rank
        plus any equipped alchemy_success_pct bonus. Tier 8's recipe is a real ladder now (1x
        each of Tier 1-7 Herb plus 1x Tier 8 Herb — see alchemy.herb_requirements), not just a
        pile of the top tier, so `needed` merges herb_requirements + bonus_ingredients into one
        dict — same shape craft_gear's own multi-material recipe already uses — rather than
        the old single herb+cost pair. Returns a dict:
          ok=False, reason=...                      — not enough herbs, nothing consumed.
          ok=True, success=True/False, ...           — attempted; success=False still cost the herbs."""
        player = self.db.get_or_create_player(user_id, name)
        required_rank = alchemy.rank_required_for_tier(tier)
        if player["alchemist_rank"] < required_rank:
            return {
                "ok": False,
                "reason": f"Tier {tier} needs Alchemist rank **{professions.rank_name(required_rank)}** "
                          f"(you're **{professions.rank_name(player['alchemist_rank'])}**) — study Alchemist with /study to advance.",
            }
        needed = {**alchemy.herb_requirements(pill_type, tier), **alchemy.bonus_ingredients(tier)}
        inventory = self.db.get_inventory(user_id)
        missing = {mat: qty for mat, qty in needed.items() if inventory.get(mat, 0) < qty}
        if missing:
            missing_text = ", ".join(f"{qty}x {mat} (have {inventory.get(mat, 0)})" for mat, qty in missing.items())
            return {"ok": False, "reason": f"Missing: {missing_text}."}

        for mat, qty in needed.items():
            self.db.remove_item(user_id, mat, qty)
        bonuses = self.compute_equipment_bonuses(user_id)
        chance = min(1.0, professions.craft_success_chance(player["alchemist_rank"]) + bonuses.get("alchemy_success_pct", 0))
        success = random.random() < chance

        # Rolled independently per material -- same "hand back one unit" shape craft_gear's
        # own salvage already uses, generalizing cleanly now that tier 8 has more than one
        # herb in the recipe (used to be a single herb refund, back when there was only ever
        # one herb to refund).
        salvage_pct = self._alchemy_salvage_bonus_pct(user_id, player)
        materials_refunded = {}
        if salvage_pct:
            for mat in needed:
                if random.random() < salvage_pct:
                    self.db.add_item(user_id, mat, 1)
                    materials_refunded[mat] = 1

        item_name = items.alchemy_pill_name(pill_type, tier)
        karma_qi = 0
        bonus_pill = False
        if success:
            self.db.add_item(user_id, item_name, 1)
            karma_qi = self._maybe_grant_genesis_lotus_karma(player)
            # Refinement Dao Path: a scaled chance at +1 extra pill on top of a successful
            # craft — distinct from alchemy_success_pct (Space Dao Path, folded into `chance`
            # above already), which only affects whether the craft succeeds at all.
            bonus_pill_chance = self.get_dao_path_totals(user_id).get("alchemy_bonus_pill_chance_pct", 0)
            if bonus_pill_chance > 0 and random.random() < bonus_pill_chance:
                self.db.add_item(user_id, item_name, 1)
                bonus_pill = True
        return {
            "ok": True, "success": success, "chance": chance,
            "item_name": item_name, "materials": needed, "materials_refunded": materials_refunded,
            "karma_qi": karma_qi, "bonus_pill": bonus_pill,
        }

    def craft_pill_multiple(self, user_id: int, name: str, pill_type: str, tier: int, attempts: int):
        """Runs up to `attempts` craft_pill calls back-to-back (e.g. Alchemy's Make 10/Make
        All buttons), stopping early once herbs run out. Returns (times_attempted,
        successes, last_result) — last_result is the final craft_pill dict, or the failing
        one if times_attempted is 0."""
        attempted = 0
        successes = 0
        last_result = None
        for _ in range(max(0, attempts)):
            result = self.craft_pill(user_id, name, pill_type, tier)
            if not result["ok"]:
                if attempted == 0:
                    return 0, 0, result
                break
            attempted += 1
            if result["success"]:
                successes += 1
            last_result = result
        return attempted, successes, last_result

    # -- Blacksmithing: /blacksmith ----------------------------------------------

    def craft_gear(self, user_id: int, name: str, gear_type: str, tier: int) -> dict:
        """Same risk model as craft_pill: consumes the recipe's ore/beast material/beast
        core regardless of outcome, then rolls success against Blacksmith rank. A
        successful forge rolls a brand new crafted_gear instance (see blacksmith.
        roll_gear_stats) rather than granting a fixed catalog item — see blacksmith.py's
        module docstring for why."""
        player = self.db.get_or_create_player(user_id, name)
        required_rank = blacksmith.rank_required_for_tier(tier)
        if player["blacksmith_rank"] < required_rank:
            return {
                "ok": False,
                "reason": f"Tier {tier} needs Blacksmith rank **{professions.rank_name(required_rank)}** "
                          f"(you're **{professions.rank_name(player['blacksmith_rank'])}**) — study Blacksmith with /study to advance.",
            }
        needed = blacksmith.recipe(tier)
        inventory = self.db.get_inventory(user_id)
        missing = {mat: qty for mat, qty in needed.items() if inventory.get(mat, 0) < qty}
        if missing:
            missing_text = ", ".join(f"{qty}x {mat} (have {inventory.get(mat, 0)})" for mat, qty in missing.items())
            return {"ok": False, "reason": f"Missing materials: {missing_text}."}

        for material, qty in needed.items():
            self.db.remove_item(user_id, material, qty)
        # Space Dao Path's crafting_success_pct + Grotto's own contribution, the blacksmith-side
        # counterpart to alchemy_success_pct (craft_pill already reads that one via
        # compute_equipment_bonuses) -- see get_crafting_success_bonus_total's own docstring.
        space_bonus = self.get_crafting_success_bonus_total(user_id)
        chance = min(1.0, professions.craft_success_chance(player["blacksmith_rank"]) + self._trait_bonus(player, "blacksmith_success_pct") + space_bonus)
        success = random.random() < chance
        # A Refinement-family root's craft_salvage_bonus_pct (see character_data.
        # CharacterTraitSpec / _alchemy_salvage_bonus_pct) — no equipped-accessory equivalent
        # exists for blacksmith the way alchemy's salvage_bonus items do, so this only ever
        # comes from a root; rolled independently per material, same "hand back one unit"
        # shape craft_pill's own herb salvage already uses.
        salvage_pct = self._alchemy_salvage_bonus_pct(user_id, player)
        materials_refunded = {}
        if salvage_pct:
            for material in needed:
                if random.random() < salvage_pct:
                    self.db.add_item(user_id, material, 1)
                    materials_refunded[material] = 1
        result = {
            "ok": True, "success": success, "chance": chance, "materials": needed,
            "materials_refunded": materials_refunded, "base_type": gear_type, "tier": tier,
        }
        if success:
            slot_type = equipment.BLACKSMITH_GEAR_SLOT_TYPE[gear_type]
            budget_bonus_pct = self._trait_bonus(player, "gear_budget_bonus_pct") + self._gu_pet_cultivation_bonus(player, "gear_budget_bonus_pct")
            stat_bonuses = blacksmith.roll_gear_stats(tier, random.Random(), budget_bonus_pct=budget_bonus_pct)
            power_score = equipment.gear_power_score_from_stats(stat_bonuses)
            gear_id = self.db.create_crafted_gear(user_id, gear_type, slot_type, tier, stat_bonuses, power_score)
            result.update({
                "gear_id": gear_id, "item_name": blacksmith.crafted_gear_display_name(gear_type, tier, gear_id),
                "stat_bonuses": stat_bonuses, "power_score": power_score,
                "karma_qi": self._maybe_grant_genesis_lotus_karma(player),
            })
        return result

    def grant_crafted_gear(self, user_id: int, name: str, gear_type: str, tier: int) -> dict:
        """/grant_gear (admin) -- unconditional version of craft_gear's own success branch:
        same real roll_gear_stats roll (a genuine random instance, not a fixed/admin-typed
        stat block), just skipping the material cost, Blacksmith-rank gate, and success-chance
        roll entirely. Deliberately no budget_bonus_pct (that's a player's own earned trait
        bonus, not something an admin grant should apply on their behalf) -- a clean roll at
        the requested tier, same as any other player would get from a lucky craft."""
        self.db.get_or_create_player(user_id, name)
        slot_type = equipment.BLACKSMITH_GEAR_SLOT_TYPE[gear_type]
        stat_bonuses = blacksmith.roll_gear_stats(tier, random.Random())
        power_score = equipment.gear_power_score_from_stats(stat_bonuses)
        gear_id = self.db.create_crafted_gear(user_id, gear_type, slot_type, tier, stat_bonuses, power_score)
        return {
            "gear_id": gear_id, "item_name": blacksmith.crafted_gear_display_name(gear_type, tier, gear_id),
            "stat_bonuses": stat_bonuses, "power_score": power_score,
        }

    def grant_manual_page(self, user_id: int, name: str, page_id: str, quantity: int = 1) -> dict:
        """/grant_manual_page (admin) -- adds page_id straight to the player's player_pages
        table, same "just give them the item, no roll/gate involved" shape as /grant_item's
        own db.add_item call. Returns {"page": manual_data.ManualPage}."""
        self.db.get_or_create_player(user_id, name)
        self.db.add_player_page(user_id, page_id, quantity)
        return {"page": manual_data.PAGES[page_id]}

    def get_player_crafted_gear(self, user_id: int) -> list:
        """Every rolled Weapon/Head/Body instance the player owns (equipped or not),
        strongest first — see equipment.py's gear_power_score_from_stats docstring for why
        this sort order matters once someone has more than a couple of these."""
        gear = self.db.get_player_crafted_gear(user_id)
        return sorted(gear, key=lambda g: -g["power_score"])

    def equip_crafted_gear(self, user_id: int, name: str, gear_id: int):
        self.db.get_or_create_player(user_id, name)
        gear = self.db.get_crafted_gear(gear_id)
        if gear is None or gear["owner_id"] != user_id:
            return False, "You don't own that piece of gear."
        slot_key = equipment.SLOT_KEY_BY_TYPE.get(gear["slot_type"])
        if slot_key is None:
            return False, "That gear type has no matching slot."
        display_name = blacksmith.crafted_gear_display_name(gear["base_type"], gear["tier"], gear["gear_id"])

        currently_equipped_gear_ids = self.db.get_equipped_gear_ids(user_id)
        if currently_equipped_gear_ids.get(slot_key) == gear_id:
            return False, f"**{display_name}** is already equipped there."

        # If this slot currently holds an ordinary catalog item (not another crafted_gear
        # instance — those don't need anything returned, the old instance stays owned via
        # its own row either way), it has to go back to inventory here same as equip_item
        # does, or swapping in a crafted instance would just silently delete it.
        if slot_key not in currently_equipped_gear_ids:
            previous_item_name = self.db.get_equipped(user_id).get(slot_key)
            if previous_item_name:
                self.db.add_item(user_id, previous_item_name, 1)

        self.db.set_equipped_instance(user_id, slot_key, gear_id, display_name)
        return True, f"Equipped **{display_name}** to {equipment.SLOT_LABEL_BY_KEY[slot_key]}."

    def equip_gu_instance(self, user_id: int, name: str, slot_key: str, instance_id: int):
        """Like equip_crafted_gear, but for a Hairy-Man-blessed gu_instances row -- takes an
        explicit slot_key (unlike equip_crafted_gear's SLOT_KEY_BY_TYPE lookup) since Gu has
        TWO possible slot_keys sharing one slot_type (gu_ability/gu_ability_2, the second only
        reachable with Twin Gu Sovereign Physique -- same backstop equip_item's own Gu-slot-2
        check uses)."""
        player = self.db.get_or_create_player(user_id, name)
        instance = self.db.get_gu_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "You don't own that blessed Gu."
        expected_type = equipment.SLOT_TYPE_BY_KEY.get(slot_key)
        if expected_type != "Gu":
            return False, "That slot doesn't exist."
        if slot_key == equipment.GU_SLOT_KEY_2 and player["physique_name"] != equipment.TWIN_GU_SOVEREIGN_PHYSIQUE_NAME:
            return False, f"{equipment.TWIN_GU_SOVEREIGN_PHYSIQUE_NAME} is required to bind a second Gu."

        currently_equipped_instance_ids = self.db.get_equipped_gu_instance_ids(user_id)
        if currently_equipped_instance_ids.get(slot_key) == instance_id:
            return False, f"**{instance['item_name']}** is already equipped there."

        # If this slot currently holds an ordinary catalog item (not another Gu instance --
        # those don't need anything returned, the old instance stays owned via its own row
        # either way), it has to go back to inventory here same as equip_item does.
        if slot_key not in currently_equipped_instance_ids:
            previous_item_name = self.db.get_equipped(user_id).get(slot_key)
            if previous_item_name:
                self.db.add_item(user_id, previous_item_name, 1)

        self.db.set_equipped_gu_instance(user_id, slot_key, instance_id, instance["item_name"])
        return True, f"Equipped your blessed **{instance['item_name']}** to {equipment.SLOT_LABEL_BY_KEY[slot_key]}."

    def dismantle_crafted_gear(self, user_id: int, name: str, gear_id: int):
        player = self.db.get_or_create_player(user_id, name)
        gear = self.db.get_crafted_gear(gear_id)
        if gear is None or gear["owner_id"] != user_id:
            return False, "You don't own that piece of gear."
        if gear_id in self.db.get_equipped_gear_ids(user_id).values():
            return False, "Unequip it first before dismantling it."

        yield_materials = blacksmith.dismantle_yield(gear["tier"])
        # A Metal-family root's gear_dismantle_refund_pct (see character_data.
        # CharacterTraitSpec) — same round()-to-nearest convention gathering.roll_quantity
        # already uses for yield_multiplier, deliberately NOT rounded up: dismantle_yield is
        # always exactly 1 per material regardless of tier, so rounding a small % bonus UP
        # would silently turn "+2%" into "+100%" every single time instead of only
        # occasionally tipping over into a bonus unit, same as any other yield roll would.
        refund_pct = self._trait_bonus(player, "gear_dismantle_refund_pct")
        if refund_pct:
            yield_materials = {mat: max(qty, round(qty * (1 + refund_pct))) for mat, qty in yield_materials.items()}
        for material, qty in yield_materials.items():
            self.db.add_item(user_id, material, qty)
        stones = blacksmith.dismantle_stones(gear["tier"])
        self.db.add_spirit_stones(user_id, stones)
        self.db.delete_crafted_gear(gear_id)
        display_name = blacksmith.crafted_gear_display_name(gear["base_type"], gear["tier"], gear["gear_id"])
        materials_text = ", ".join(f"{qty}x {mat}" for mat, qty in yield_materials.items())
        return True, f"Dismantled **{display_name}** — recovered {materials_text} and {format_number(stones)} spirit stones."

    # -- Accessories/artifacts (see accessories_data.py, the insanity accessories and
    # artifacts design doc) — equip/unequip/attune/salvage plus the "active" mechanics that
    # need an explicit trigger (essence sips, rerolls, breakthrough boosts, weekly
    # refreshes). Passive stat_bonuses ride the exact same compute_equipment_bonuses/
    # _qi_rate_components path crafted_gear/manuals already extended; encounter-start
    # buffs, defeat wards, and the two "next reward" mechanics are separate hooks combat
    # code and the reward-granting code call into directly (see hunt.py/discovery_gen
    # integration below in this file).

    ACCESSORY_ARTIFACT_SLOT_TYPES = {
        "ring_1": "Ring", "ring_2": "Ring", "earring_1": "Earring", "earring_2": "Earring",
        "necklace": "Necklace", "bracelet": "Bracelet", "artifact_1": "Artifact", "artifact_2": "Artifact",
    }
    MAX_ATTUNEMENT_POINTS_BASE = 2  # "two mortal attunements or one immortal attunement" (section 2)
    EXCLUSIVE_EFFECT_KEYS = {"defeat_ward_daily", "loot_duplicate_daily"}  # Major Trigger limit (section 2)
    ENCOUNTER_BUFF_DURATION_SECONDS = 90
    SALVAGE_STONES_PER_RANK_RARITY_STAR = 15

    def max_attunement_points(self, player_row: dict) -> int:
        """Attunement capacity scales with the player's own progress -- +1 on top of the base
        2 per Great Realm reached (0 at Qi Condensation, up to +6 at Ancient Realm), per
        explicit request."""
        great_realm_index = realms.STAGES[player_row["realm_index"]].great_realm_index
        return self.MAX_ATTUNEMENT_POINTS_BASE + great_realm_index

    def _affix_for_instance(self, instance: dict):
        return accessories_data.ITEMS.get(instance["item_id"]) if instance else None

    def _accessory_display_name(self, instance: dict, affix) -> str:
        return f"{affix.name} #{instance['instance_id']}"

    def get_player_accessories_artifacts(self, user_id: int) -> list:
        """[{**instance, "affix": Affix}, ...], rarest/highest-rank first."""
        rarity_rank = {r: i for i, r in enumerate(accessories_data.RARITY_ORDER)}
        enriched = []
        for inst in self.db.get_player_accessory_instances(user_id):
            affix = self._affix_for_instance(inst)
            if affix is not None:
                enriched.append({**inst, "affix": affix})
        enriched.sort(key=lambda e: (-rarity_rank.get(e["affix"].rarity, 0), -e["affix"].rank))
        return enriched

    def grant_accessory_artifact(self, user_id: int, name: str, item_id: str) -> dict:
        self.db.get_or_create_player(user_id, name)
        instance_id = self.db.create_accessory_instance(user_id, item_id)
        return {"instance_id": instance_id, "affix": accessories_data.ITEMS[item_id]}

    def roll_and_grant_accessory_artifact(self, user_id: int, name: str, source_key: str, source_rank: int, theme_tags: list):
        """Used by loot integration (hunt/raid kills, /search discovery steps) — returns the
        granted {"instance_id", "affix"} dict, or None if this roll simply didn't produce
        one (see accessories_gen.roll_category)."""
        affix = accessories_gen.roll_accessory_or_artifact(source_key, source_rank, theme_tags, random.Random())
        if affix is None:
            return None
        return self.grant_accessory_artifact(user_id, name, affix.item_id)

    def equip_accessory_artifact(self, user_id: int, name: str, slot_key: str, instance_id: int):
        player = self.db.get_or_create_player(user_id, name)
        expected_type = self.ACCESSORY_ARTIFACT_SLOT_TYPES.get(slot_key)
        if expected_type is None:
            return False, "That slot doesn't accept accessories or artifacts."
        instance = self.db.get_accessory_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "You don't own that item."
        affix = self._affix_for_instance(instance)
        if affix is None:
            return False, "That item no longer exists."
        if affix.slot_type != expected_type:
            return False, f"**{affix.name}** doesn't fit in the {equipment.SLOT_LABEL_BY_KEY[slot_key]} slot."
        if affix.rarity in accessories_data.ATTUNEMENT_REQUIRED_RARITIES and not instance["attuned"]:
            return False, f"**{affix.name}** needs attunement first — see /accessories."

        equipped_ids = self.db.get_equipped_accessory_ids(user_id)
        if equipped_ids.get(slot_key) == instance_id:
            return False, f"**{affix.name}** is already equipped there."

        if affix.effect_key in self.EXCLUSIVE_EFFECT_KEYS:
            for other_slot, other_id in equipped_ids.items():
                if other_slot == slot_key:
                    continue
                other_affix = self._affix_for_instance(self.db.get_accessory_instance(other_id))
                if other_affix and other_affix.effect_key == affix.effect_key:
                    label = affix.effect_key.replace("_", " ")
                    return False, f"Only one **{label}** item may be equipped at a time — unequip **{other_affix.name}** first."

        # A displaced catalog item (if any) goes back to inventory — same rule
        # equip_crafted_gear/equip_item already follow.
        if slot_key not in equipped_ids:
            previous_item_name = self.db.get_equipped(user_id).get(slot_key)
            if previous_item_name:
                self.db.add_item(user_id, previous_item_name, 1)

        display_name = self._accessory_display_name(instance, affix)
        self.db.set_equipped_accessory(user_id, slot_key, instance_id, display_name)
        return True, f"Equipped **{display_name}** to {equipment.SLOT_LABEL_BY_KEY[slot_key]}."

    def unequip_accessory_artifact(self, user_id: int, name: str, slot_key: str):
        self.db.get_or_create_player(user_id, name)
        item_name = self.db.get_equipped(user_id).get(slot_key)
        if not item_name:
            return False, "That slot is already empty."
        self.db.clear_equipped(user_id, slot_key)
        return True, f"Unequipped **{item_name}** from {equipment.SLOT_LABEL_BY_KEY[slot_key]}."

    def attune_accessory_artifact(self, user_id: int, name: str, instance_id: int):
        player = self.db.get_or_create_player(user_id, name)
        instance = self.db.get_accessory_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "You don't own that item."
        if instance["attuned"]:
            return False, "Already attuned."
        affix = self._affix_for_instance(instance)
        if affix is None or affix.rarity not in accessories_data.ATTUNEMENT_REQUIRED_RARITIES:
            return False, "That item doesn't require attunement."
        cost = accessories_data.attunement_cost(affix)
        max_points = self.max_attunement_points(player)
        if player["attunement_points_used"] + cost > max_points:
            return False, f"Not enough attunement capacity ({player['attunement_points_used']}/{max_points} used) — unattune something first."
        self.db.set_accessory_instance_attuned(instance_id)
        self.db.add_attunement_points(user_id, cost)
        return True, f"Attuned to **{affix.name}**."

    def _release_attunement(self, user_id: int, instance: dict):
        """Refunds this instance's attunement cost and clears its attuned flag if it was
        attuned -- shared by unattune_accessory_artifact and salvage_accessory_artifact.
        Trading/gambling an attuned item away is handled directly in GameDatabase's own
        execute_trade/execute_gamble transfer logic (same refund, computed there since the
        item is changing owners inside an already-open transaction). No-op if not attuned."""
        if not instance["attuned"]:
            return
        affix = self._affix_for_instance(instance)
        cost = accessories_data.attunement_cost(affix) if affix else 1
        self.db.add_attunement_points(user_id, -cost)
        self.db.set_accessory_instance_unattuned(instance["instance_id"])

    def unattune_accessory_artifact(self, user_id: int, name: str, instance_id: int):
        self.db.get_or_create_player(user_id, name)
        instance = self.db.get_accessory_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "You don't own that item."
        if not instance["attuned"]:
            return False, "That item isn't attuned."
        if instance_id in self.db.get_equipped_accessory_ids(user_id).values():
            return False, "Unequip it first before unattuning it."
        affix = self._affix_for_instance(instance)
        self._release_attunement(user_id, instance)
        return True, f"Unattuned from **{affix.name if affix else 'that item'}** — capacity freed up."

    def salvage_accessory_artifact(self, user_id: int, name: str, instance_id: int):
        self.db.get_or_create_player(user_id, name)
        instance = self.db.get_accessory_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "You don't own that item."
        if instance_id in self.db.get_equipped_accessory_ids(user_id).values():
            return False, "Unequip it first before salvaging it."
        affix = self._affix_for_instance(instance)
        if affix is None:
            return False, "That item no longer exists."
        if affix.rarity == "Unique":
            return False, "Unique items can't normally be salvaged."
        self._release_attunement(user_id, instance)
        rarity_star = accessories_data.RARITY_ORDER.index(affix.rarity) + 1
        stones = affix.rank * rarity_star * self.SALVAGE_STONES_PER_RANK_RARITY_STAR
        self.db.add_spirit_stones(user_id, stones)
        self.db.delete_accessory_instance(instance_id)
        return True, f"Salvaged **{affix.name}** for {format_number(stones)} 🪙 spirit stones."

    def salvage_all_accessory_artifact_duplicates(self, user_id: int, name: str, item_id: str) -> dict:
        """/accessories' 'Salvage All' -- salvages every owned instance sharing the same
        item_id (e.g. every extra 'Dew-Gathering Jade Ring'), skipping whichever ones are
        currently equipped, using the exact same per-item rules/math as
        salvage_accessory_artifact (Unique rarity is never salvageable at all, so a Unique
        item_id simply has nothing eligible)."""
        self.db.get_or_create_player(user_id, name)
        equipped_ids = set(self.db.get_equipped_accessory_ids(user_id).values())
        owned = [e for e in self.get_player_accessories_artifacts(user_id) if e["affix"].item_id == item_id]
        if not owned:
            return {"ok": False, "reason": "You don't own that item."}
        affix = owned[0]["affix"]
        eligible = [e for e in owned if e["instance_id"] not in equipped_ids and affix.rarity != "Unique"]
        skipped_equipped = sum(1 for e in owned if e["instance_id"] in equipped_ids)
        if not eligible:
            reason = "Unique items can't normally be salvaged." if affix.rarity == "Unique" else "That's currently equipped — unequip it first before salvaging it."
            return {"ok": False, "reason": reason}
        rarity_star = accessories_data.RARITY_ORDER.index(affix.rarity) + 1
        stones_each = affix.rank * rarity_star * self.SALVAGE_STONES_PER_RANK_RARITY_STAR
        for entry in eligible:
            instance = self.db.get_accessory_instance(entry["instance_id"])
            self._release_attunement(user_id, instance)
            self.db.delete_accessory_instance(entry["instance_id"])
        total_stones = stones_each * len(eligible)
        self.db.add_spirit_stones(user_id, total_stones)
        return {
            "ok": True, "name": affix.name, "count": len(eligible),
            "stones": total_stones, "skipped_equipped": skipped_equipped,
        }

    def _accessory_cooldown_ready(self, instance: dict, weekly: bool = False) -> int:
        """Seconds remaining before this instance's daily/weekly-gated mechanic is ready
        again — rolling window from last_activation_ts (see the module's daily/weekly
        adaptation note in accessories_data.py's docstring), 0 if ready now."""
        window = 7 * 86400 if weekly else 86400
        remaining = instance["last_activation_ts"] + window - int(time.time())
        return max(0, remaining)

    def activate_accessory_artifact(self, user_id: int, name: str, instance_id: int):
        """Manual-trigger active mechanics: essence_restore_charges, search_reroll_daily,
        breakthrough_boost_daily, refresh_artifact_weekly, unique_signature. (extra_loot_roll/
        loot_duplicate/defeat_ward/encounter_shield/post_action_buff all trigger
        automatically at the moment they're relevant instead — see the hooks below.)"""
        player = self.db.get_or_create_player(user_id, name)
        instance = self.db.get_accessory_instance(instance_id)
        if instance is None or instance["owner_id"] != user_id:
            return False, "You don't own that item."
        if instance_id not in self.db.get_equipped_accessory_ids(user_id).values():
            return False, "Equip it first before activating it."
        affix = self._affix_for_instance(instance)
        if affix is None:
            return False, "That item no longer exists."
        params = affix.effect_params
        weekly = bool(params.get("weekly"))

        if affix.effect_key == "essence_restore_charges":
            now = int(time.time())
            charges_used = instance["charges_used"]
            if instance["charges_reset_ts"] + 86400 <= now:
                charges_used = 0
            max_charges = params.get("charges", 1)
            if charges_used >= max_charges:
                return False, f"**{affix.name}** is out of charges for today."
            self.db.set_accessory_instance_charges(instance_id, charges_used + 1, now if charges_used == 0 else instance["charges_reset_ts"])
            gained = self._restore_essence_pct(user_id, params.get("pct", 0.1))
            return True, f"**{affix.name}**: restored {format_number(gained, decimals=0)} primeval essence ({max_charges - charges_used - 1} charge(s) left today)."

        if affix.effect_key == "search_reroll_daily":
            # Adaptation: rerolling a specific past roll's exact outcome has no clean hook
            # (search/discovery results aren't stored after the fact), so this grants one
            # bonus /search charge instead — a "second chance" in the same spirit. Uses the
            # SAME charges_used/charges_reset_ts multi-charge tracking as essence_restore_
            # charges above (not the generic single-timestamp _accessory_cooldown_ready gate
            # below) so a "charges": N item like Truth-Hearing Pearl ("Three uses per day")
            # actually gets N uses/day instead of silently being capped at 1 -- a live bug
            # fixed 2026-08-13.
            now = int(time.time())
            window = 7 * 86400 if weekly else 86400
            charges_used = instance["charges_used"]
            if instance["charges_reset_ts"] + window <= now:
                charges_used = 0
            max_charges = params.get("charges", 1)
            if charges_used >= max_charges:
                from .ui_utils import format_duration
                remaining = instance["charges_reset_ts"] + window - now
                return False, f"**{affix.name}** is out of charges — ready again in {format_duration(remaining)}."
            self.db.set_accessory_instance_charges(instance_id, charges_used + 1, now if charges_used == 0 else instance["charges_reset_ts"])
            settled = self._settle_search_charges(user_id)
            new_charges = min(search_data.SEARCH_MAX_CHARGES, settled["search_charges"] + 1)
            self.db.set_search_charges(user_id, new_charges, settled["search_charges_last_ts"])
            left_note = f" ({max_charges - charges_used - 1} charge(s) left)" if max_charges > 1 else ""
            return True, f"**{affix.name}**: granted a bonus search charge ({new_charges}/{search_data.SEARCH_MAX_CHARGES}){left_note}."

        remaining = self._accessory_cooldown_ready(instance, weekly)
        if remaining > 0:
            from .ui_utils import format_duration
            return False, f"**{affix.name}** is still on cooldown — ready in {format_duration(remaining)}."

        if affix.effect_key == "breakthrough_boost_daily":
            # Blood-Debt Ring's flavor ("sacrifice HP to increase the next CULTIVATION
            # gain") is really a /cultivate boost, not an attempt_breakthrough one — its
            # hp_cost_pct/cultivation_pct params are handled as an immediate HP cost plus a
            # short qi-rate buff (reusing the existing buff system) instead of the
            # pending-breakthrough mechanism the chance_pct/cost_reduction_pct items use.
            if "cultivation_pct" in params:
                hp_cost = round(player["hp"] * params.get("hp_cost_pct", 0))
                if player["hp"] - hp_cost < player["max_hp"] * 0.30:
                    return False, f"**{affix.name}** needs at least 30% HP to activate."
                self.db.set_hp(user_id, player["hp"] - hp_cost)
                self.db.add_buff(user_id, affix.name, params["cultivation_pct"], 600)
                self.db.set_accessory_instance_activation(instance_id, int(time.time()))
                return True, f"**{affix.name}**: sacrificed {format_number(hp_cost)} HP for +{params['cultivation_pct']*100:.0f}% cultivation gain for the next 10 minutes."
            boost = {}
            if "chance_pct" in params:
                boost["chance_pct"] = params["chance_pct"]
            if "cost_reduction_pct" in params:
                boost["cost_reduction_pct"] = params["cost_reduction_pct"]
            self.db.set_pending_breakthrough_boost(user_id, boost)
            self.db.set_accessory_instance_activation(instance_id, int(time.time()))
            return True, f"**{affix.name}** activated — your next breakthrough attempt is boosted."

        if affix.effect_key == "refresh_artifact_weekly":
            # Adaptation: no UI exists to "pick which other daily effect to refresh" (a live
            # dead-effect bug fixed 2026-08-13 -- this used to just print that instruction and
            # burn its own weekly cooldown for nothing), so this uses the same "grants a bonus
            # /search charge" simplification search_reroll_daily items already use instead.
            settled = self._settle_search_charges(user_id)
            new_charges = min(search_data.SEARCH_MAX_CHARGES, settled["search_charges"] + 1)
            self.db.set_search_charges(user_id, new_charges, settled["search_charges_last_ts"])
            self.db.set_accessory_instance_activation(instance_id, int(time.time()))
            return True, f"**{affix.name}**: refreshes early, granting a bonus search charge ({new_charges}/{search_data.SEARCH_MAX_CHARGES})."

        if affix.effect_key == "unique_signature":
            if affix.effect_params.get("handler") == "echo_sword":
                # Automatic (see apply_encounter_start_bonuses' ECHO_SWORD_ATK_PCT branch),
                # not a manual trigger -- a live dead-effect bug fixed 2026-08-13 used to have
                # this print a flavor message and burn a daily cooldown for no real effect.
                return False, f"**{affix.name}** doesn't have a manual activation — its echo strike triggers automatically each encounter."
            ok, message = self._activate_unique_signature(user_id, name, instance, affix)
            if ok:
                self.db.set_accessory_instance_activation(instance_id, int(time.time()))
            return ok, message

        return False, f"**{affix.name}** doesn't have a manual activation — it triggers automatically."

    def _restore_essence_pct(self, user_id: int, pct: float, allow_overflow: bool = False) -> float:
        gained, _, _ = self.db.restore_essence_percent(user_id, pct, allow_overflow=allow_overflow)
        return gained

    # -- Rank 6-7 Unique-rarity signature effects (hand-authored per item, per the design
    # doc's own "Unique: hand-authored" framing rather than a generic mechanic) -----------

    def _activate_unique_signature(self, user_id: int, name: str, instance: dict, affix):
        handler = affix.effect_params.get("handler")
        if handler == "ring_of_trials":
            state = instance["state"]
            stacks = state.get("failure_insight_stacks", 0)
            if stacks < 10:
                return False, f"**{affix.name}**: only {stacks}/10 Failure Insight stacks — gained automatically after a failed breakthrough."
            self.db.set_pending_breakthrough_boost(user_id, {"chance_pct": 1.0})
            self.db.set_accessory_instance_state(instance["instance_id"], {"failure_insight_stacks": 0})
            return True, f"**{affix.name}**: consumed all 10 stacks — your next breakthrough is guaranteed to succeed."
        if handler == "echo_earrings":
            # Adaptation: a full cross-item "Echo token" ledger (gain one whenever ANY other
            # daily artifact triggers, spend three to refresh a different item) has no clean
            # hook without threading state through activate_accessory_artifact/
            # apply_encounter_start_bonuses/check_and_consume_defeat_ward/
            # roll_bonus_discovery_reward all at once -- a live dead-effect bug fixed
            # 2026-08-13 (this used to just print a flavor message with no real effect at
            # all), fixed with the same "grants a bonus /search charge" simplification
            # search_reroll_daily/refresh_artifact_weekly items already use.
            settled = self._settle_search_charges(user_id)
            new_charges = min(search_data.SEARCH_MAX_CHARGES, settled["search_charges"] + 1)
            self.db.set_search_charges(user_id, new_charges, settled["search_charges_last_ts"])
            return True, f"**{affix.name}**: an Echo token resonates, granting a bonus search charge ({new_charges}/{search_data.SEARCH_MAX_CHARGES})."
        if handler == "scale_of_exchange":
            # Adaptation: no multi-item sacrifice/category-picker UI exists (a live
            # dead-effect bug fixed 2026-08-13 -- this used to just print that instruction
            # with no real effect), so this drops the sacrifice input requirement the same
            # way this file's own Poison-Drinking Gourd precedent already does (see
            # accessories_data.py's own adaptation note) and directly manifests one random
            # non-Unique accessory or artifact of this item's own rank instead.
            rng = random.Random()
            category = rng.choice(["Accessory", "Artifact"])
            weights = accessories_data.ACCESSORY_RARITY_WEIGHTS if category == "Accessory" else accessories_data.ARTIFACT_RARITY_WEIGHTS
            non_unique_weights = {r: w for r, w in weights.items() if r != "Unique"}
            rarity = accessories_gen.weighted_choice(non_unique_weights, rng)
            chosen = accessories_gen.select_item(category, affix.rank, rarity, [], rng)
            if chosen is None:
                return True, f"**{affix.name}** hums with power, but the exchange yields nothing this time."
            grant = self.grant_accessory_artifact(user_id, name, chosen.item_id)
            return True, f"**{affix.name}** hums with power and manifests **{grant['affix'].name}**!"
        return True, f"**{affix.name}** activated."

    def record_failed_breakthrough_insight(self, user_id: int):
        """Ring of the Ten-Thousand-Trial Survivor's passive half — called by
        attempt_breakthrough on every failure, regardless of whether the ring is equipped."""
        equipped_ids = self.db.get_equipped_accessory_ids(user_id)
        for instance_id in equipped_ids.values():
            instance = self.db.get_accessory_instance(instance_id)
            affix = self._affix_for_instance(instance)
            if affix and affix.effect_params.get("handler") == "ring_of_trials":
                state = instance["state"]
                state["failure_insight_stacks"] = min(10, state.get("failure_insight_stacks", 0) + 1)
                self.db.set_accessory_instance_state(instance_id, state)

    def consume_pending_breakthrough_boost(self, user_id: int, player: dict) -> dict:
        raw = player["pending_breakthrough_boost"]
        if not raw:
            return {}
        self.db.set_pending_breakthrough_boost(user_id, None)
        return json.loads(raw)

    # "Sword That Returns Before It Leaves" (see accessories_data.py's unique_signature
    # echo_sword handler) -- its own flavor ("first sword attack each encounter resolves
    # twice, once normal and once as a weaker echo") is an automatic per-encounter proc, not
    # a manual activation, so it rides this same hook instead of activate_accessory_artifact's
    # unique_signature dispatch (which now just tells the player it's automatic -- see there).
    ECHO_SWORD_ATK_PCT = 0.15

    def apply_encounter_start_bonuses(self, user_id: int, name: str):
        """Called once at the start of a /hunt, /raid, /pvp, /battlefield,
        /inheritance_ground, or /search_black_heaven fight -- grants the short combat buff
        for every equipped encounter_shield/post_action_buff item (see the module docstring's
        "first N enemy actions" -> time-boxed-buff adaptation note), unconditionally, every
        single encounter.

        Live bug fixed 2026-08-13: this used to also gate on _accessory_cooldown_ready, the
        SAME daily/weekly cooldown activate_accessory_artifact's manually-triggered daily
        effects use. These items' own flavor text is explicit ("Once per encounter"), and
        this function is called once per NEW encounter (hunt.py/raid.py/battlefield_view.py/
        inheritance_ground_view.py/black_heaven_search_view.py each call it exactly once per
        fight, never mid-round), so the daily gate was pure copy-paste leftover from the
        manual-activation pattern -- it silently throttled roughly two dozen "once per
        encounter" accessories/artifacts down to firing once per REAL-WORLD DAY total,
        no matter how many separate fights (or separate battle bubbles within one
        Inheritance Ground run) a player actually had that day."""
        for instance_id in self.db.get_equipped_accessory_ids(user_id).values():
            instance = self.db.get_accessory_instance(instance_id)
            affix = self._affix_for_instance(instance)
            if affix is None:
                continue
            is_echo_sword = affix.effect_key == "unique_signature" and affix.effect_params.get("handler") == "echo_sword"
            if affix.effect_key not in ("encounter_shield", "post_action_buff") and not is_echo_sword:
                continue
            params = affix.effect_params
            duration = params.get("duration_seconds", self.ENCOUNTER_BUFF_DURATION_SECONDS)
            atk_pct = self.ECHO_SWORD_ATK_PCT if is_echo_sword else params.get("atk_pct", 0)
            self.db.add_buff(
                user_id, affix.name, 0, duration,
                str_bonus=params.get("str_pct", 0) * 100 if params.get("str_pct") else 0,
                atk_bonus=atk_pct * 100 if atk_pct else 0,
                def_bonus=(params.get("reduction_pct", 0) or params.get("def_pct", 0)) * 100,
                spd_bonus=params.get("spd_pct", 0) * 100,
            )
        # Combat-Mode Gu Pet upkeep -- see _drain_active_gu_pet_combat_dispatch's own
        # docstring for why this rides the same "once per new encounter" hook.
        self._drain_active_gu_pet_combat_dispatch(user_id)

    def check_and_consume_flee_ward(self, user_id: int) -> Optional[str]:
        """Nine-Deaths Black Pearl only (see accessories_data.py's flee_on_defeat_unlimited
        effect) -- checked BEFORE check_and_consume_defeat_ward wherever a killing blow would
        apply (see hunt.py/battlefield_view.py). Unlike defeat_ward_daily (still records a
        defeat, just negates the Qi loss), this resolves the whole encounter as a successful
        flee/withdraw instead -- no defeat, no Qi loss, same "bank what you'd earned so far"
        outcome a manual Flee/Withdraw already produces. Returns the ward's name if it fired,
        else None. No cooldown at all -- fires every single time it's needed (by explicit
        request, superseding the item's original once-every-seven-days limit), so there's
        nothing to check against last_activation_ts and nothing to record here either. Scoped
        to solo-player encounters (hunt/battlefield) only -- in a team battle or the backstab
        duel, a knocked-out participant already stops taking further damage while the fight
        continues for the rest of the team, which is the closest real equivalent "escape"
        already available there."""
        for instance_id in self.db.get_equipped_accessory_ids(user_id).values():
            instance = self.db.get_accessory_instance(instance_id)
            affix = self._affix_for_instance(instance)
            if affix is None or affix.effect_key != "flee_on_defeat_unlimited":
                continue
            return affix.name
        return None

    def check_and_consume_defeat_ward(self, user_id: int) -> Optional[str]:
        """Called wherever a defeat's Qi-loss penalty would apply (see hunt.py) — returns
        the ward's name if one fired (caller should skip the penalty and survive at 1 HP
        instead), else None."""
        for instance_id in self.db.get_equipped_accessory_ids(user_id).values():
            instance = self.db.get_accessory_instance(instance_id)
            affix = self._affix_for_instance(instance)
            if affix is None or affix.effect_key != "defeat_ward_daily":
                continue
            weekly = bool(affix.effect_params.get("weekly"))
            if self._accessory_cooldown_ready(instance, weekly) > 0:
                continue
            self.db.set_accessory_instance_activation(instance_id, int(time.time()))
            # Life-Retaining Vermilion Ring's own drawback ("lose 20% current essence") --
            # previously never actually charged (a live bug fixed 2026-08-13, making the
            # ring strictly better than advertised). Read AFTER set_accessory_instance_
            # activation above so the ward itself always fires regardless of essence level.
            essence_cost_pct = affix.effect_params.get("essence_cost_pct", 0)
            if essence_cost_pct > 0:
                player = self.db.get_player_row(user_id)
                cost = round(player["primeval_essence"] * essence_cost_pct) if player else 0
                if cost > 0:
                    self.db.add_primeval_essence(user_id, -cost)
            return affix.name
        return None

    # White Heaven Escape Gu (see game/content/canon_gu_white_heaven.py) is a "near-perfect
    # escape Gu" by explicit request -- the closest existing mechanic is Worldly Escape Gu's
    # own once-daily death-penalty negation, so it shares that exact check rather than
    # inventing a second, parallel daily-flag system for what's functionally the same ask.
    WORLDLY_ESCAPE_GU_NAMES = ("Worldly Escape Gu", "White Heaven Escape Gu")

    def check_and_consume_worldly_escape(self, user_id: int) -> Optional[str]:
        """Worldly Escape Gu (see world_boss.py) — "once per day, ignore the penalty from
        one PvP defeat or failed dangerous exploration." Retargeted to hunt/raid/battlefield's
        real death Qi-loss penalty instead of PvP specifically: PvP defeat in this game
        already costs nothing (see pvp_view.py's own "it's just a duel, no real harm done"),
        so there's no PvP penalty left to negate — this is the actual, existing combat-defeat
        penalty the doc's flavor text was gesturing at. Checked alongside (and after)
        check_and_consume_defeat_ward — an accessory ward still takes priority since it's the
        more specific, pre-existing mechanic. Returns the equipped Gu's own name (Worldly
        Escape Gu or White Heaven Escape Gu) on activation, so callers can log the real name
        instead of a hardcoded one, or None if it didn't trigger."""
        gu_name = self.db.get_equipped(user_id).get("gu_ability")
        if not gu_name:
            return None
        # Equipped Gu names carry a "(Quality)" suffix (e.g. "White Heaven Escape Gu
        # (Immortal)") -- parse_gu_name strips it for the comparison, same convention as
        # _white_heaven_travel_seconds above; the RETURNED name stays the full display name
        # (gu_name itself), which reads better in a log line either way.
        family = equipment.parse_gu_name(gu_name)[0] or gu_name
        if family not in self.WORLDLY_ESCAPE_GU_NAMES:
            return None
        return gu_name if self.db.try_use_daily_gu_penalty_negation(user_id) else None

    def roll_bonus_discovery_reward(self, user_id: int, name: str, reward_grant_fn) -> Optional[str]:
        """Called after a discovery's FINAL-step reward is granted (see resolve_discovery_step)
        — if an equipped extra_loot_roll_daily/loot_duplicate_daily item is off cooldown,
        rolls (or duplicates) one more reward via reward_grant_fn and returns its text."""
        for instance_id in self.db.get_equipped_accessory_ids(user_id).values():
            instance = self.db.get_accessory_instance(instance_id)
            affix = self._affix_for_instance(instance)
            if affix is None or affix.effect_key not in ("extra_loot_roll_daily", "loot_duplicate_daily"):
                continue
            if self._accessory_cooldown_ready(instance) > 0:
                continue
            self.db.set_accessory_instance_activation(instance_id, int(time.time()))
            bonus_text = reward_grant_fn()
            return f"{affix.name}: {bonus_text}"
        return None

    # -- Manual/Inheritance/Secret Realm/Dream Realm system ------------------------------
    # A separate, slower discovery loop alongside /explore (see search_data.py's module
    # docstring) — /search finds clues, encounters, and (rarely) inheritances/secret
    # realms/dream realms; /inheritance, /realm, /dream enter and resolve whatever's
    # currently active; /manual studies, assembles, refines, equips, and dismantles pages
    # and manuals. See manual_data.py and discovery_gen.py for the actual tables/algorithms
    # this just calls into.

    MANUAL_ASSEMBLE_INK_COST_PER_SLOT = 3
    MANUAL_STUDY_DUST_COST = 2
    # Design doc section 5 originally called for 1 hour at the lowest realm scaling to 12
    # hours at the highest, later cut to a sixth of that (10 minutes to 2 hours) for still
    # feeling too punishing, and cut again (flat, no more per-rank scaling) since experimenting
    # with manual loadouts should be near-frictionless, not gated behind a growing timer.
    MANUAL_CHANGE_COOLDOWN_SECONDS = 60

    def _effective_search_recharge_seconds(self, user_id: int) -> int:
        """search_recharge_reduction_pct (see accessories_data.py's clue_chance-effect items
        and this class's own SPECIAL_BONUS_KEYS comment) shaves a little off how long each
        /search charge takes to refill. Capped at 50% off so no combination of items can make
        recharge instant."""
        reduction = min(0.5, self.compute_equipment_bonuses(user_id).get("search_recharge_reduction_pct", 0))
        return max(60, round(search_data.SEARCH_RECHARGE_SECONDS * (1 - reduction)))

    def _settle_search_charges(self, user_id: int) -> dict:
        status = dict(self.db.get_search_status(user_id))
        now = int(time.time())
        charges = status["search_charges"]
        last_ts = status["search_charges_last_ts"] or now
        interval = self._effective_search_recharge_seconds(user_id)
        if charges < search_data.SEARCH_MAX_CHARGES:
            gained = max(0, now - last_ts) // interval
            if gained > 0:
                charges = min(search_data.SEARCH_MAX_CHARGES, charges + gained)
                last_ts = last_ts + gained * interval
                self.db.set_search_charges(user_id, charges, last_ts)
        status["search_charges"] = charges
        status["search_charges_last_ts"] = last_ts
        return status

    def get_search_status(self, user_id: int, name: str) -> dict:
        player = self.db.get_or_create_player(user_id, name)
        status = self._settle_search_charges(user_id)
        now = int(time.time())
        seconds_to_next = 0
        if status["search_charges"] < search_data.SEARCH_MAX_CHARGES:
            seconds_to_next = max(0, self._effective_search_recharge_seconds(user_id) - (now - status["search_charges_last_ts"]))
        active_discovery = self.db.get_discovery(status["active_discovery_id"]) if status["active_discovery_id"] else None
        great_realm_index = realms.STAGES[player["realm_index"]].great_realm_index
        return {
            "player": player,
            "charges": status["search_charges"],
            "max_charges": search_data.SEARCH_MAX_CHARGES,
            "seconds_to_next_charge": seconds_to_next,
            "momentum": status["discovery_momentum"],
            "focus": status["search_focus"],
            "active_discovery": active_discovery,
            "available_regions": search_data.available_regions(great_realm_index),
        }

    def set_search_focus(self, user_id: int, name: str, focus: str) -> bool:
        self.db.get_or_create_player(user_id, name)
        if focus not in search_data.SEARCH_FOCUS_OPTIONS:
            return False
        self.db.set_search_focus(user_id, focus)
        return True

    def _grant_insight_dust(self, user_id: int, base_amount: int) -> int:
        """Applies an equipped manual's insight_gain_pct bonus (see manual_view.EFFECT_LABELS)
        on top of base_amount before crediting it, rounding up so a nonzero bonus is never
        silently lost to truncation on small grants. Returns the actual amount granted."""
        bonus_pct = self.compute_equipment_bonuses(user_id).get("insight_gain_pct", 0)
        amount = math.ceil(base_amount * (1 + bonus_pct)) if bonus_pct else base_amount
        self.db.add_insight_dust(user_id, amount)
        return amount

    def _apply_region_reward_bonus(self, user_id: int, name: str, reward: dict) -> dict:
        """Folds a player's world_region passive into a reward dict just before granting it
        (see _grant_reward) -- Eastern Sea boosts tiered materials, Western Desert boosts
        spirit stones and ink/dust, Central Continent boosts ink/dust and has a real chance to
        grant an extra copy of an already-rolled page. Unrecognized kinds/regions pass
        through untouched; never mutates the caller's own dict."""
        player = self.db.get_or_create_player(user_id, name)
        bonus = self._region_bonus_dict(player)
        if not bonus:
            return reward
        kind = reward.get("kind")
        if kind == "stones" and "reward_stone_multiplier" in bonus:
            reward = dict(reward)
            reward["amount"] = round(reward["amount"] * bonus["reward_stone_multiplier"])
        elif kind == "manual_currency" and "reward_ink_dust_multiplier" in bonus:
            mult = bonus["reward_ink_dust_multiplier"]
            reward = dict(reward)
            reward["ink"] = round(reward["ink"] * mult)
            reward["dust"] = round(reward["dust"] * mult)
        elif kind == "pages" and bonus.get("reward_page_bonus_chance") and reward.get("page_ids"):
            if random.random() < bonus["reward_page_bonus_chance"]:
                reward = dict(reward)
                reward["page_ids"] = list(reward["page_ids"]) + [random.choice(reward["page_ids"])]
        elif kind == "item" and bonus.get("reward_material_multiplier") and reward.get("item_name") and gathering.item_tier(reward["item_name"]) is not None:
            reward = dict(reward)
            reward["quantity"] = round(reward["quantity"] * bonus["reward_material_multiplier"])
        return reward

    def _grant_reward(self, user_id: int, name: str, reward: dict) -> str:
        reward = self._apply_region_reward_bonus(user_id, name, reward)
        kind = reward["kind"]
        if kind == "stones":
            self.db.add_spirit_stones(user_id, reward["amount"])
            return f"{format_number(reward['amount'])} 🪙 spirit stones"
        if kind == "item":
            if not reward.get("item_name"):
                self.db.add_spirit_stones(user_id, 20)
                return "20 🪙 spirit stones (nothing else fit)"
            self.db.add_item(user_id, reward["item_name"], reward["quantity"])
            return f"{reward['quantity']}x **{reward['item_name']}**"
        if kind == "pages":
            page_ids = reward["page_ids"]
            if not page_ids:
                granted = self._grant_insight_dust(user_id, 3)
                return f"{granted} insight dust (no matching pages found)"
            for page_id in page_ids:
                self.db.add_player_page(user_id, page_id, 1)
            names = ", ".join(
                f"{manual_data.PAGES[pid].name} (R{manual_data.PAGES[pid].rank})"
                for pid in page_ids if pid in manual_data.PAGES
            )
            return f"page(s): {names}"
        if kind == "manual":
            manual = reward["manual"]
            manual_id = self.db.create_manual(user_id, manual)
            return f"a complete manual: **{manual['name']}** (Rank {manual['rank']} {manual['rarity']}, id {manual_id})"
        if kind == "crafted_gear":
            # Same rolled-instance path as a successful /blacksmith forge (see craft_gear) —
            # loot-dropped weapon/armor rewards are the same underlying gear, so they get the
            # same unique id + random stats instead of a separate static item.
            slot_type = equipment.BLACKSMITH_GEAR_SLOT_TYPE[reward["base_type"]]
            power_score = equipment.gear_power_score_from_stats(reward["stat_bonuses"])
            gear_id = self.db.create_crafted_gear(user_id, reward["base_type"], slot_type, reward["tier"], reward["stat_bonuses"], power_score)
            display_name = blacksmith.crafted_gear_display_name(reward["base_type"], reward["tier"], gear_id)
            return f"**{display_name}** — {equipment.describe_stat_bonuses(reward['stat_bonuses'])}"
        if kind == "clue":
            # A key/clue found INSIDE a discovery (as opposed to /search's own clue-track
            # system) — folded into a small Ink grant rather than a whole second clue
            # mechanic layered inside the first one.
            self.db.add_manual_ink(user_id, 2)
            return "2 manual ink (a fragment of something bigger)"
        if kind == "insight":
            granted = self._grant_insight_dust(user_id, reward["amount"])
            return f"{granted} insight dust"
        if kind == "manual_currency":
            self.db.add_manual_ink(user_id, reward["ink"])
            granted = self._grant_insight_dust(user_id, reward["dust"])
            return f"{reward['ink']} manual ink + {granted} insight dust"
        return "nothing"

    def _maybe_apply_luck_tide(self, player, category: str, source_key: str, location_rank: int, rng: random.Random):
        """Giant Sun Inheritor Root's Luck Tide — once daily, the first /search minor_find or
        encounter reward is rerolled (a plain do-over, not a compare-and-keep-better: the
        heterogeneous reward kinds generate_loot can return — stones vs. items vs. Gu — have
        no single "which is bigger" ordering to compare across, so this reroll always takes
        the SECOND result, same "second result is final" framing the design brief's other
        reroll mechanics already use). Returns (reward, used) — reward is unchanged and
        used=False if this root/charge doesn't apply."""
        root_spec = chargen.get_root_spec(player["root_name"])
        if not root_spec or root_spec.name != "Giant Sun Inheritor Root":
            return None, False
        if not self.db.try_use_unique_daily_charge(player["user_id"]):
            return None, False
        reward = discovery_gen.generate_loot(category, source_key, location_rank, "Standard", [], rng)
        return reward, True

    def run_search(self, user_id: int, name: str, region: str = None) -> dict:
        status = self.get_search_status(user_id, name)
        if status["active_discovery"] is not None:
            return {"ok": False, "reason": "active_discovery", "discovery": status["active_discovery"]}
        if status["charges"] < 1:
            return {"ok": False, "reason": "no_charges", "seconds_to_next_charge": status["seconds_to_next_charge"]}

        settled = self._settle_search_charges(user_id)
        was_full = settled["search_charges"] >= search_data.SEARCH_MAX_CHARGES
        new_charges = settled["search_charges"] - 1
        new_last_ts = int(time.time()) if was_full else settled["search_charges_last_ts"]
        self.db.set_search_charges(user_id, new_charges, new_last_ts)

        region = region if region in status["available_regions"] else status["available_regions"][-1]
        location_rank = search_data.region_rank(region)
        rng = random.Random()

        search_bonuses = self.compute_equipment_bonuses(user_id)
        clue_bonus = search_bonuses.get("clue_chance_bonus_pct", 0)
        dream_realm_bias = self._trait_bonus(status["player"], "dream_realm_bias_pct")
        outcome = discovery_gen.roll_search_result(status["momentum"], status["focus"], rng, clue_bonus=clue_bonus, dream_realm_bias=dream_realm_bias)
        self.db.set_discovery_momentum(user_id, outcome["momentum_after"])
        result_type = outcome["result"]

        if result_type in search_data.SPECIAL_RESULTS:
            difficulty = discovery_gen.roll_difficulty(rng, quality_bias=self._trait_bonus(status["player"], "discovery_quality_bias_pct"))
            theme = discovery_gen.theme_for_discovery(result_type, rng)
            expires = int(time.time()) + search_data.DISCOVERY_EXPIRY_SECONDS[result_type]
            discovery_id = self.db.create_discovery(user_id, {
                "type": result_type, "theme": theme["name"], "rank": location_rank,
                "difficulty": difficulty, "seed": rng.randrange(1, 2**31), "expires_at": expires,
            })
            karma_qi = self._maybe_grant_genesis_lotus_karma(status["player"])
            return {
                "ok": True, "result": result_type, "region": region, "discovery_id": discovery_id,
                "theme": theme, "rank": location_rank, "difficulty": difficulty, "karma_qi": karma_qi,
            }

        if result_type == "nothing":
            # Void Star Root's daily_nothing_upgrade (see character_data.CharacterTraitSpec) —
            # once per UTC day, turn this dud into a real minor_find instead.
            root_spec = chargen.get_root_spec(status["player"]["root_name"])
            if root_spec and root_spec.daily_nothing_upgrade and self.db.try_use_daily_search_upgrade(user_id):
                category = discovery_gen.weighted_choice({"cultivation_resource": 60, "spirit_stones": 40}, rng)
                reward = discovery_gen.generate_loot(category, "minor_find", location_rank, "Standard", [], rng)
                reward_text = self._grant_reward(user_id, name, reward)
                return {"ok": True, "result": "minor_find", "region": region, "reward_text": f"{reward_text} (upgraded by your root)"}
            return {"ok": True, "result": "nothing", "region": region}

        if result_type == "minor_find":
            category = discovery_gen.weighted_choice({"cultivation_resource": 60, "spirit_stones": 40}, rng)
            reward = discovery_gen.generate_loot(category, "minor_find", location_rank, "Standard", [], rng)
            rerolled, luck_tide_used = self._maybe_apply_luck_tide(status["player"], category, "minor_find", location_rank, rng)
            reward = rerolled if luck_tide_used else reward
            reward_text = self._grant_reward(user_id, name, reward)
            if luck_tide_used:
                reward_text += " (Luck Tide rerolled this)"
            return {"ok": True, "result": "minor_find", "region": region, "reward_text": reward_text}

        if result_type == "encounter":
            category = discovery_gen.weighted_choice({"rare_material_bundle": 40, "wild_gu": 25, "spirit_stones": 35}, rng)
            reward = discovery_gen.generate_loot(category, "encounter", location_rank, "Standard", [], rng)
            rerolled, luck_tide_used = self._maybe_apply_luck_tide(status["player"], category, "encounter", location_rank, rng)
            reward = rerolled if luck_tide_used else reward
            reward_text = self._grant_reward(user_id, name, reward)
            if luck_tide_used:
                reward_text += " (Luck Tide rerolled this)"
            return {"ok": True, "result": "encounter", "region": region, "reward_text": reward_text}

        if result_type == "clue":
            # A Space-family root's secret_realm_clue_chance_pct (see character_data.
            # CharacterTraitSpec) shifts weight off the inheritance pool and onto the secret
            # realm pool before picking a theme — same "move N of 100 weight points" trick
            # discovery_gen.roll_search_result's own clue_bonus already uses, just applied to
            # WHICH kind of clue rather than whether one happens at all.
            secret_realm_bias = self._trait_bonus(status["player"], "secret_realm_clue_chance_pct")
            inh_weight = len(search_data.INHERITANCE_THEMES)
            sr_weight = len(search_data.SECRET_REALM_THEMES)
            if secret_realm_bias > 0:
                shift = min(inh_weight, secret_realm_bias * 100)
                inh_weight -= shift
                sr_weight += shift
            pool = rng.choices([search_data.INHERITANCE_THEMES, search_data.SECRET_REALM_THEMES], weights=[inh_weight, sr_weight], k=1)[0]
            theme = rng.choice(pool)
            discovery_type = "inheritance" if theme in search_data.INHERITANCE_THEMES else "secret_realm"
            required = search_data.CLUE_FRAGMENTS_REQUIRED
            track = self.db.add_clue_fragment(user_id, discovery_type, theme["name"], required, location_rank)
            if track["fragments"] >= track["fragments_required"]:
                self.db.clear_clue_track(track["track_id"])
                self.db.set_discovery_momentum(user_id, 0)  # completing a clue track IS discovering a special location
                difficulty = discovery_gen.roll_difficulty(rng, quality_bias=self._trait_bonus(status["player"], "discovery_quality_bias_pct"))
                expires = int(time.time()) + search_data.DISCOVERY_EXPIRY_SECONDS[discovery_type]
                discovery_id = self.db.create_discovery(user_id, {
                    "type": discovery_type, "theme": theme["name"], "rank": max(location_rank, track["guaranteed_rank"]),
                    "difficulty": difficulty, "seed": rng.randrange(1, 2**31), "expires_at": expires,
                })
                return {
                    "ok": True, "result": "clue_completed", "region": region, "discovery_id": discovery_id,
                    "theme": theme, "discovery_type": discovery_type,
                }
            return {
                "ok": True, "result": "clue", "region": region, "theme": theme["name"],
                "fragments": track["fragments"], "fragments_required": track["fragments_required"],
            }

        return {"ok": True, "result": result_type, "region": region}

    def _theme_tags_for(self, discovery_type: str, theme_name: str) -> list:
        table = {
            "inheritance": search_data.INHERITANCE_THEMES,
            "secret_realm": search_data.SECRET_REALM_THEMES,
            "dream_realm": search_data.DREAM_REALM_FORMS,
            "battlefield": search_data.BATTLEFIELD_THEMES,
            "region_dream_realm": search_data.REGION_DREAM_REALM_THEMES,
        }[discovery_type]
        match = next((t for t in table if t["name"] == theme_name), None)
        return match.get("tags", []) if match else []

    # discovery["type"] -> how /discovery should resolve it: "steps" for the existing
    # room-by-room DiscoveryView loop, "battlefield" for BattlefieldView's wave combat,
    # "stat_check" for RegionDreamRealmView's single stat roll.
    DISCOVERY_ENTRY_KIND = {
        "inheritance": "steps", "secret_realm": "steps", "dream_realm": "steps",
        "battlefield": "battlefield", "region_dream_realm": "stat_check",
    }

    def enter_discovery(self, user_id: int, name: str) -> dict:
        player = self.db.get_or_create_player(user_id, name)
        discovery_id = player["active_discovery_id"]
        if not discovery_id:
            return {"ok": False, "reason": "none_active"}
        discovery = self.db.get_discovery(discovery_id)
        if discovery is None or (discovery["expires_at"] and discovery["expires_at"] < int(time.time())):
            self.db.clear_active_discovery(user_id, discovery_id)
            return {"ok": False, "reason": "expired"}
        # active_discovery_id stays set for the discovery's WHOLE lifetime (only
        # finish_discovery/abandon_discovery ever clear it), so without this a player with
        # several /search messages open (all showing the same pending discovery, since it's a
        # single per-player slot) could click "Enter Discovery" on each one -- every click
        # would succeed and hand back a fresh, independently-playable DiscoveryView/
        # BattlefieldView/RegionDreamRealmView for the SAME discovery, each capable of
        # granting its own full rewards. try_enter_discovery is a single atomic
        # UPDATE...WHERE status='open' rather than a separate read-then-write, so two
        # near-simultaneous clicks can't both slip through the gap between checking and
        # setting status -- only one caller ever actually wins the transition to "entered".
        if not self.db.try_enter_discovery(discovery_id):
            return {"ok": False, "reason": "already_entered"}
        kind = self.DISCOVERY_ENTRY_KIND[discovery["type"]]
        result = {"ok": True, "discovery": discovery, "kind": kind}
        if kind == "steps":
            result["total_steps"] = search_data.DISCOVERY_STEP_COUNT[discovery["type"]]
        return result

    # discovery type + is_final -> accessories_data.LOOT_SOURCE_TABLE key
    ACCESSORY_SOURCE_KEY_BY_DISCOVERY = {
        ("inheritance", False): "inheritance_room", ("inheritance", True): "inheritance_final",
        ("secret_realm", False): "secret_realm_room", ("secret_realm", True): "secret_realm_final",
        ("dream_realm", False): "dream_realm_stage", ("dream_realm", True): "dream_realm_final",
    }

    def resolve_discovery_step(self, user_id: int, name: str, discovery: dict, step_index: int, total_steps: int) -> dict:
        self.db.get_or_create_player(user_id, name)
        rng = random.Random(discovery["seed"] + step_index)  # deterministic per step, still varies room-to-room
        theme_tags = self._theme_tags_for(discovery["type"], discovery["theme"])
        # ">=" rather than an exact "==" -- self-healing if step_index ever overshoots
        # total_steps - 1 for any reason (e.g. a duplicate/stale button click resolving one
        # extra step after the discovery already should have finished). An exact equality
        # check meant an overshoot could never become true again, permanently trapping a
        # discovery in an unfinishable loop (observed live: a discovery still going at step 51
        # of a 3-step type) -- discovery_view.py's own _on_continue now also guards against
        # the specific duplicate-click trigger, but this is the actual fix for the "can never
        # recover" part.
        is_final = step_index >= total_steps - 1
        step = discovery_gen.resolve_step(discovery["type"], discovery["rank"], discovery["difficulty"], theme_tags, rng, is_final)
        reward_text = self._grant_reward(user_id, name, step["reward"])

        # A step's room/event/chest can ALSO independently turn up an accessory or artifact
        # (see accessories_data.LOOT_SOURCE_TABLE) — this is on top of, not instead of, the
        # step's normal reward above.
        source_key = self.ACCESSORY_SOURCE_KEY_BY_DISCOVERY.get((discovery["type"], is_final))
        accessory_grant = self.roll_and_grant_accessory_artifact(user_id, name, source_key, discovery["rank"], theme_tags) if source_key else None
        if accessory_grant:
            reward_text += f" ...and **{accessory_grant['affix'].name}**!"

        bonus_text = None
        if is_final:
            def _reroll_final_reward():
                bonus_reward = discovery_gen.resolve_step(discovery["type"], discovery["rank"], discovery["difficulty"], theme_tags, random.Random(), True)["reward"]
                return self._grant_reward(user_id, name, bonus_reward)
            bonus_text = self.roll_bonus_discovery_reward(user_id, name, _reroll_final_reward)

        # Essence Restoration Pill: rare bonus roll for Secret Realm and Dream Realm steps
        # specifically (not Inheritance -- see items.roll_essence_restoration_pill_drop's own
        # docstring for why this moved here instead of the Alchemist craft table).
        if discovery["type"] in ("secret_realm", "dream_realm"):
            essence_pill = roll_essence_restoration_pill_drop()
            if essence_pill:
                pill_name, pill_qty = essence_pill
                self.db.add_item(user_id, pill_name, pill_qty)
                reward_text += f" ...and {pill_qty}x rare **{pill_name}**!"

        # Persist how far this discovery has actually progressed -- see the steps_completed
        # column comment in database.py. Skipped on the final step: finish_discovery (called
        # right after this returns, see DiscoveryView._on_continue) deletes the whole
        # discovery row a moment later anyway, so there's nothing left to persist onto.
        if not is_final:
            self.db.increment_discovery_steps_completed(discovery["discovery_id"])

        return {
            "name": step["name"], "category": step["category"], "reward": step["reward"],
            "reward_text": reward_text, "is_final": is_final, "bonus_reward_text": bonus_text,
        }

    def reopen_discovery(self, discovery_id: int):
        """Called when a player backs out of a discovery via "Back to Search" without
        finishing or abandoning it (DiscoveryView/RegionDreamRealmView's own _on_back_to_search
        -- BattlefieldView has no such button, it has no legitimate "leave and resume" path at
        all) -- resets status back to "open" so a later Enter Discovery click can resume it,
        without reopening the hole enter_discovery's own already-entered refusal exists to
        close: the OLD view already called self.stop() before this runs, so it can never grant
        a second, parallel set of rewards after this."""
        self.db.set_discovery_status(discovery_id, "open")

    def finish_discovery(self, user_id: int, discovery_id: int):
        self.db.set_discovery_status(discovery_id, "completed")
        self.db.clear_active_discovery(user_id, discovery_id)

    def abandon_discovery(self, user_id: int, discovery_id: int):
        self.db.clear_active_discovery(user_id, discovery_id)

    # -- Battlefield discoveries (see battlefield_view.BattlefieldView) --------------------
    # A small per-wave trickle reward, then a bigger final payout on defeat/withdrawal scaled
    # by how many waves were actually cleared -- "rewards are determined by how many rounds
    # the cultivator completed."

    BATTLEFIELD_WAVE_REWARD_CATEGORIES = {"cultivation_resource": 50, "spirit_stones": 50}
    BATTLEFIELD_FINAL_REWARD_CATEGORIES = {
        "rare_material_bundle": 25, "spirit_stones": 20, "wild_gu": 15, "weapon": 10,
        "armor": 10, "manual_page_bundle": 15, "manual_currency_bundle": search_data.MANUAL_CURRENCY_BUNDLE_WEIGHT,
    }
    BATTLEFIELD_FINAL_REWARD_SCALE_PER_WAVE = 0.20

    def resolve_battlefield_wave_clear(self, user_id: int, name: str, discovery: dict, wave_number: int) -> str:
        rng = random.Random(discovery["seed"] + wave_number)
        theme_tags = self._theme_tags_for("battlefield", discovery["theme"])
        category = discovery_gen.weighted_choice(self.BATTLEFIELD_WAVE_REWARD_CATEGORIES, rng)
        reward = discovery_gen.generate_loot(category, "encounter", discovery["rank"], discovery["difficulty"], theme_tags, rng)
        reward_text = self._grant_reward(user_id, name, reward)
        # Essence Restoration Pill: rare bonus roll per wave (see items.
        # roll_essence_restoration_pill_drop's own docstring for why this moved here instead
        # of the Alchemist craft table).
        essence_pill = roll_essence_restoration_pill_drop()
        if essence_pill:
            pill_name, pill_qty = essence_pill
            self.db.add_item(user_id, pill_name, pill_qty)
            reward_text += f" ...and {pill_qty}x rare **{pill_name}**!"
        return reward_text

    def resolve_battlefield_final_reward(self, user_id: int, name: str, discovery: dict, waves_cleared: int) -> str:
        rng = random.Random(discovery["seed"] + 9000 + waves_cleared)
        theme_tags = self._theme_tags_for("battlefield", discovery["theme"])
        bonus_rank = min(manual_data.MAX_MANUAL_RANK, discovery["rank"] + waves_cleared // 2)
        category = discovery_gen.weighted_choice(self.BATTLEFIELD_FINAL_REWARD_CATEGORIES, rng)
        reward = discovery_gen.generate_loot(category, "secret_realm_boss", bonus_rank, discovery["difficulty"], theme_tags, rng)
        scale = 1 + self.BATTLEFIELD_FINAL_REWARD_SCALE_PER_WAVE * waves_cleared
        if reward["kind"] == "stones":
            reward["amount"] = round(reward["amount"] * scale)
        elif reward["kind"] == "manual_currency":
            reward["ink"] = round(reward["ink"] * scale)
            reward["dust"] = round(reward["dust"] * scale)
        elif reward["kind"] == "item" and reward.get("quantity"):
            reward["quantity"] = max(reward["quantity"], round(reward["quantity"] * scale))
        reward_text = self._grant_reward(user_id, name, reward)
        essence_pill = roll_essence_restoration_pill_drop()
        if essence_pill:
            pill_name, pill_qty = essence_pill
            self.db.add_item(user_id, pill_name, pill_qty)
            reward_text += f" ...and {pill_qty}x rare **{pill_name}**!"
        return reward_text

    def start_battlefield(self, user_id: int, name: str) -> dict:
        """/battlefield -- a direct, cooldown-gated entry point into the same wave-combat
        BattlefieldView normally only turns up opportunistically via /search or /region
        actions (see maybe_trigger_region_discovery). Rolled the exact same way (rank =
        the player's own current location rank, so battlefields naturally get harder as the
        player's realm climbs; difficulty and theme rolled the same way too) — this command
        just skips the RNG gate and opens one immediately instead of waiting to stumble onto
        one. Still respects the single active-discovery slot rather than silently clobbering
        an unrelated /search find still waiting to be entered.

        Returns {"ok": False, "reason": "cooldown", "remaining_seconds"} or
        {"ok": False, "reason": "active_discovery"} or {"ok": True, "discovery": {...}}."""
        player = self.db.get_or_create_player(user_id, name)
        remaining = self._check_cooldown(player, "last_battlefield_ts", self.BATTLEFIELD_COOLDOWN_SECONDS)
        if remaining > 0:
            return {"ok": False, "reason": "cooldown", "remaining_seconds": remaining}
        if player["active_discovery_id"]:
            return {"ok": False, "reason": "active_discovery"}

        rng = random.Random()
        theme = rng.choice(search_data.BATTLEFIELD_THEMES)
        rank = self._player_location_rank(player)
        difficulty = discovery_gen.roll_difficulty(rng, quality_bias=self._trait_bonus(player, "discovery_quality_bias_pct"))
        expires = int(time.time()) + search_data.DISCOVERY_EXPIRY_SECONDS["battlefield"]
        discovery_id = self.db.create_discovery(user_id, {
            "type": "battlefield", "theme": theme["name"], "rank": rank,
            "difficulty": difficulty, "seed": rng.randrange(1, 2**31), "expires_at": expires,
        })
        self.db.set_discovery_status(discovery_id, "entered")
        self.db.set_timestamp_column(user_id, "last_battlefield_ts", int(time.time()))
        return {"ok": True, "discovery": self.db.get_discovery(discovery_id)}

    # -- Region dream realms (see region_dream_realm_view.RegionDreamRealmView) ------------
    # "Stat checks checking if the cultivator's speed, attack, defense, or luck is good
    # enough for the reward" -- distinct from /search's own narrative-stage dream realms
    # (DiscoveryView's room-by-room loop), which are untouched by this.

    REGION_DREAM_REALM_BASE_THRESHOLD_BY_RANK = {1: 20, 2: 35, 3: 55, 4: 80, 5: 110, 6: 150, 7: 200}
    REGION_DREAM_REALM_DIFFICULTY_MULTIPLIER = {"Safe": 0.8, "Standard": 1.0, "Dangerous": 1.25, "Forbidden": 1.6}
    REGION_DREAM_REALM_MIN_PASS_CHANCE = 0.05
    REGION_DREAM_REALM_MAX_PASS_CHANCE = 0.95
    REGION_DREAM_REALM_REWARD_CATEGORIES = {
        "high_quality_pages": 35, "breakthrough_page": 15, "dream_gu": 15, "dream_material": 15,
        "manual_currency_bundle": search_data.MANUAL_CURRENCY_BUNDLE_WEIGHT,
    }

    def resolve_region_dream_realm(self, user_id: int, name: str, discovery: dict) -> dict:
        """Single-shot: rolls the trial's stat check once and returns
        {"passed", "stat_label", "effective_stat", "threshold", "reward_text"}."""
        player = self.db.get_or_create_player(user_id, name)
        rng = random.Random(discovery["seed"])
        theme = next((t for t in search_data.REGION_DREAM_REALM_THEMES if t["name"] == discovery["theme"]), search_data.REGION_DREAM_REALM_THEMES[0])
        stat_key = theme["stat"]
        stats_bonus = self.compute_equipment_bonuses(user_id)["stats"]
        effective_stat = player[stat_key] + stats_bonus.get(stat_key, 0)
        base_threshold = self.REGION_DREAM_REALM_BASE_THRESHOLD_BY_RANK.get(discovery["rank"], 200)
        threshold = base_threshold * self.REGION_DREAM_REALM_DIFFICULTY_MULTIPLIER.get(discovery["difficulty"], 1.0)
        pass_chance = max(self.REGION_DREAM_REALM_MIN_PASS_CHANCE, min(self.REGION_DREAM_REALM_MAX_PASS_CHANCE, effective_stat / threshold))
        passed = rng.random() < pass_chance
        theme_tags = self._theme_tags_for("region_dream_realm", discovery["theme"])
        if passed:
            category = discovery_gen.weighted_choice(self.REGION_DREAM_REALM_REWARD_CATEGORIES, rng)
            reward = discovery_gen.generate_loot(category, "dream_completion", discovery["rank"], discovery["difficulty"], theme_tags, rng)
            reward_text = self._grant_reward(user_id, name, reward)
        else:
            granted = self._grant_insight_dust(user_id, rng.randint(3, 8))
            reward_text = f"{granted} insight dust (dream soul damage; partial insight retained)"
        self.finish_discovery(user_id, discovery["discovery_id"])
        return {
            "passed": passed, "stat_label": stat_key, "effective_stat": effective_stat,
            "threshold": round(threshold), "reward_text": reward_text,
        }

    # -- Manual pages: study, refine, dismantle -------------------------------------------

    def get_player_pages(self, user_id: int) -> dict:
        return self.db.get_player_pages(user_id)

    def study_page(self, user_id: int, name: str, page_id: str):
        self.db.get_or_create_player(user_id, name)
        owned = self.db.get_player_pages(user_id).get(page_id)
        if not owned:
            return False, "You don't own that page."
        if owned["studied"]:
            return False, "Already studied."
        if not self.db.spend_insight_dust(user_id, self.MANUAL_STUDY_DUST_COST):
            return False, f"Needs {self.MANUAL_STUDY_DUST_COST} insight dust."
        self.db.set_page_studied(user_id, page_id)
        page = manual_data.PAGES.get(page_id)
        return True, f"Studied **{page.name if page else page_id}** — tags, effect, and any visible flaw are now revealed."

    def refine_page(self, user_id: int, name: str, page_id: str):
        self.db.get_or_create_player(user_id, name)
        owned = self.db.get_player_pages(user_id).get(page_id)
        if not owned:
            return False, "You don't own that page."
        current = owned["refinement_level"]
        next_level = manual_data.NEXT_REFINEMENT.get(current)
        if next_level is None:
            return False, "Already at the highest refinement level."
        required = manual_data.REFINEMENT_SPEC[next_level].duplicate_requirement
        if owned["quantity"] < required + 1:  # +1 keeps the working copy itself
            spare = max(0, owned["quantity"] - 1)
            return False, (
                f"Needs {required} duplicate cop{'y' if required == 1 else 'ies'} on top of your working copy "
                f"({required + 1} total) — you have {owned['quantity']} total ({spare} spare)."
            )
        self.db.remove_player_page(user_id, page_id, required)
        self.db.set_page_refinement(user_id, page_id, next_level)
        page = manual_data.PAGES.get(page_id)
        return True, f"**{page.name if page else page_id}** refined to **{next_level}**!"

    def dismantle_page(self, user_id: int, name: str, page_id: str, quantity: int = 1):
        self.db.get_or_create_player(user_id, name)
        page = manual_data.PAGES.get(page_id)
        if page is None:
            return False, "Unknown page."
        owned = self.db.get_player_pages(user_id).get(page_id, {}).get("quantity", 0)
        quantity = min(quantity, owned)
        if quantity <= 0:
            return False, f"You don't own **{page.name}**."
        self.db.remove_player_page(user_id, page_id, quantity)
        ink = max(1, page.rank) * quantity
        self.db.add_manual_ink(user_id, ink)
        return True, f"Dismantled {quantity}x **{page.name}** for {ink} manual ink."

    # -- Manual assembly, equip, dismantle -------------------------------------------------

    def get_player_manuals(self, user_id: int) -> list:
        return self.db.get_player_manuals(user_id)

    def assemble_manual(self, user_id: int, name: str, page_ids: list):
        player = self.db.get_or_create_player(user_id, name)
        owned = self.db.get_player_pages(user_id)
        pages = []
        for page_id in page_ids:
            page = manual_data.PAGES.get(page_id)
            if page is None:
                return False, f"Unknown page {page_id}.", None
            if owned.get(page_id, {}).get("quantity", 0) < 1:
                return False, f"You don't own **{page.name}**.", None
            pages.append(page)
        categories = {p.category for p in pages}
        if len(pages) < 2 or "Foundation" not in categories or "Circulation" not in categories:
            return False, "A manual needs exactly one Foundation page and one Circulation page, plus anything else you want to add.", None

        # Average, not max -- one Rank 7 page mixed into an otherwise low-rank build no longer
        # inherits a Rank 7 power budget it didn't earn (that page's own strong base_effects
        # still apply either way; only the BUDGET this manual gets to spend changes). sql_round
        # matches SQLite's own "round half away from zero" so this reads predictably rather
        # than Python's banker's-rounding surprising anyone at the x.5 boundary.
        rank = max(1, min(manual_data.MAX_MANUAL_RANK, chargen.sql_round(sum(p.rank for p in pages) / len(pages))))
        ink_cost = self.MANUAL_ASSEMBLE_INK_COST_PER_SLOT * len(pages)
        if not self.db.spend_manual_ink(user_id, ink_cost):
            return False, f"Needs {ink_cost} manual ink to assemble {len(pages)} pages (you have {player['manual_ink']}).", None

        primary_path = pages[0].tags[0] if pages[0].tags else "qi"
        rng = random.Random()
        # Craft-time rarity roll (see manual_data.ASSEMBLE_RARITY_WEIGHTS) -- unlike a
        # loot-generated manual's rarity (fixed by its source before this ever runs), an
        # assembled manual's rarity is randomized fresh on every craft, deliberately far more
        # generous odds than loot (Unique here is 10%, not loot's 0.3%) since this is the
        # payoff for the player's own page choices. Feeds RARITY_EFFICIENCY (the "extra
        # multiplier") and RARITY_DEFECT_CHANCE (a lucky high roll also flaws less) below,
        # exactly the same way it already does for generate_manual's loot path.
        # Ink-Spitter Cicada's (or Balance-Furnace Toad's) own manual_rarity_bonus_pct (see
        # gu_pet.roll_specialty_bonus) shifts these weights toward the higher-rarity end
        # before the roll (see manual_data.weighted_rarity_choices) -- a no-op dict copy for
        # everyone without an active Cultivation-Mode Cicada/Toad pet.
        rarity_bonus_pct = self._gu_pet_cultivation_bonus(player, "manual_rarity_bonus_pct")
        rarity_weights = manual_data.weighted_rarity_choices(manual_data.ASSEMBLE_RARITY_WEIGHTS, rarity_bonus_pct)
        rarity = rng.choices(list(rarity_weights), weights=list(rarity_weights.values()))[0]
        root_spec = chargen.get_root_spec(player["root_name"])
        coherence = manual_gen.calculate_coherence(
            pages, primary_path,
            bonus_tags=root_spec.manual_coherence_tags if root_spec else None,
            bonus_categories=root_spec.manual_coherence_categories if root_spec else None,
            flat_bonus=root_spec.manual_coherence_flat if root_spec else 0,
        )
        band = manual_data._coherence_band(coherence)
        # Refinement payoff (see manual_data.REFINEMENT_SPEC) -- computed from `owned` BEFORE
        # the pages get spent below, since it's the specific copies being consumed that earn
        # this, not the page catalog entries in the abstract.
        bonus = manual_gen.refinement_bonus_totals(pages, owned)
        effects = manual_gen.resolve_manual_effects(pages, rank, rarity, coherence, effectiveness_mult=bonus["effectiveness_mult"])
        flaws = manual_gen.roll_flaws(pages, rarity, coherence, rng)
        rolled_flaw_count = len(flaws)
        if flaws and bonus["flaw_repair_chance"]:
            flaws = [f for f in flaws if rng.random() >= bonus["flaw_repair_chance"]]
        repaired_flaw_count = rolled_flaw_count - len(flaws)
        secondary_paths = sorted({tag for p in pages for tag in p.tags if tag != primary_path})[:5]
        manual_name = manual_gen.generate_manual_name(primary_path, pages, "assembled", rng)
        stability = max(0, min(100, 100 - band.deviation_modifier - 8 * len(flaws) + bonus["stability_bonus"]))

        manual_dict = {
            "name": manual_name, "rank": rank, "rarity": rarity, "primary_path": primary_path,
            "secondary_paths": secondary_paths, "page_ids": [p.page_id for p in pages],
            "coherence": coherence, "coherence_band": band.label, "stability": stability,
            "comprehension": 0, "effects": effects, "flaws": flaws, "generation_seed": 0, "bound": False,
            "refinement_effect_mult": bonus["effectiveness_mult"],
        }
        for page_id in page_ids:
            self.db.remove_player_page(user_id, page_id, 1)
        manual_id = self.db.create_manual(user_id, manual_dict)
        manual_dict["manual_id"] = manual_id

        refinement_bits = []
        if bonus["effectiveness_mult"] > 1.0:
            refinement_bits.append(f"+{(bonus['effectiveness_mult'] - 1) * 100:.0f}% effect strength")
        if bonus["stability_bonus"]:
            refinement_bits.append(f"+{bonus['stability_bonus']} stability")
        if repaired_flaw_count:
            refinement_bits.append(f"{repaired_flaw_count} flaw{'s' if repaired_flaw_count != 1 else ''} repaired")
        refinement_note = f" Refinement bonus: {', '.join(refinement_bits)}." if refinement_bits else ""
        rarity_note = f" ✨ Rolled **{rarity}** quality!" if rarity != "Common" else ""
        return True, f"Assembled **{manual_name}** — Rank {rank}, {band.label} coherence ({coherence}/100).{rarity_note}{refinement_note}", manual_dict

    def equip_manual(self, user_id: int, name: str, manual_id: int, slot: str):
        player = self.db.get_or_create_player(user_id, name)
        manual = self.db.get_manual(manual_id)
        if manual is None or manual["owner_id"] != user_id:
            return False, "You don't own that manual."
        if slot not in ("primary", "auxiliary"):
            return False, "Invalid manual slot."
        other_slot_id = player["equipped_auxiliary_manual_id"] if slot == "primary" else player["equipped_primary_manual_id"]
        if other_slot_id == manual_id:
            return False, "That manual is already equipped in your other slot."
        remaining = self._check_cooldown(player, "last_manual_change_ts", self.MANUAL_CHANGE_COOLDOWN_SECONDS)
        if remaining > 0:
            from .ui_utils import format_duration
            return False, f"Manuals are still settling from your last change — try again in {format_duration(remaining)}."
        self.db.set_equipped_manual(user_id, slot, manual_id)
        self.db.set_manual_bound(manual_id)
        self.db.set_timestamp_column(user_id, "last_manual_change_ts", int(time.time()))
        return True, f"Equipped **{manual['name']}** as your {slot} manual."

    def unequip_manual(self, user_id: int, name: str, slot: str):
        self.db.get_or_create_player(user_id, name)
        if slot not in ("primary", "auxiliary"):
            return False, "Invalid manual slot."
        self.db.set_equipped_manual(user_id, slot, None)
        self.db.set_timestamp_column(user_id, "last_manual_change_ts", int(time.time()))
        return True, f"Unequipped your {slot} manual."

    # -- Equipment presets (save/restore a full loadout by name — /preset_save afk,
    # /preset_load raid, etc.) --------------------------------------------------------------

    # Every real equip slot a preset snapshots — excludes the legacy "manual" slot_key
    # (equipment.py's own note: dead, never populated by any current character). Manuals
    # ride the two dedicated players.equipped_*_manual_id columns instead, snapshotted
    # separately (see save_equipment_preset/_apply_preset_manuals below).
    EQUIPMENT_PRESET_SLOT_KEYS = [key for key, _, _, _ in equipment.SLOTS if key != "manual"]
    MAX_EQUIPMENT_PRESETS = 5

    @staticmethod
    def _normalize_preset_name(preset_name: str):
        """Returns (preset_key, display_name) — key is what's stored/looked-up by (so
        "AFK" and "afk" are the same preset), display_name preserves the casing the player
        actually typed."""
        display_name = (preset_name or "").strip()[:30]
        return display_name.lower(), display_name

    def save_equipment_preset(self, user_id: int, name: str, preset_name: str):
        player = self.db.get_or_create_player(user_id, name)
        preset_key, display_name = self._normalize_preset_name(preset_name)
        if not preset_key:
            return False, "Give your preset a name, e.g. `/preset_save afk`."

        existing = self.db.get_equipment_presets(user_id)
        is_overwrite = any(p["preset_key"] == preset_key for p in existing)
        if not is_overwrite and len(existing) >= self.MAX_EQUIPMENT_PRESETS:
            return False, f"You can only have {self.MAX_EQUIPMENT_PRESETS} presets saved — delete one first with `/preset_delete`."

        equipped = self.db.get_equipped(user_id)
        gear_ids = self.db.get_equipped_gear_ids(user_id)
        accessory_ids = self.db.get_equipped_accessory_ids(user_id)
        slots = {}
        for slot_key in self.EQUIPMENT_PRESET_SLOT_KEYS:
            item_name = equipped.get(slot_key)
            if not item_name:
                continue
            slots[slot_key] = {
                "item_name": item_name,
                "gear_id": gear_ids.get(slot_key),
                "accessory_instance_id": accessory_ids.get(slot_key),
            }

        self.db.save_equipment_preset(
            user_id, preset_key, display_name, slots,
            player["equipped_primary_manual_id"], player["equipped_auxiliary_manual_id"],
        )
        verb = "Updated" if is_overwrite else "Saved"
        return True, f"{verb} your current loadout as preset **{display_name}** ({len(slots)} gear slot(s) + manuals)."

    def get_equipment_presets(self, user_id: int) -> list:
        return self.db.get_equipment_presets(user_id)

    def delete_equipment_preset(self, user_id: int, preset_name: str):
        preset_key, display_name = self._normalize_preset_name(preset_name)
        preset = self.db.get_equipment_preset(user_id, preset_key)
        if preset is None:
            return False, f"No preset named **{display_name}**."
        self.db.delete_equipment_preset(user_id, preset_key)
        return True, f"Deleted preset **{preset['display_name']}**."

    def _apply_preset_manuals(self, user_id: int, name: str, player: dict, preset: dict) -> Optional[str]:
        """Applies preset["primary_manual_id"]/["auxiliary_manual_id"] as ONE cooldown-gated
        change instead of two independent equip_manual calls — the first call's cooldown
        stamp would otherwise immediately block the second, and writing both slots directly
        also lets a clean "swap the two manuals" preset apply in one shot instead of
        tripping equip_manual's own "already equipped in your other slot" guard."""
        target_primary = preset["primary_manual_id"]
        target_aux = preset["auxiliary_manual_id"]
        current_primary = player["equipped_primary_manual_id"]
        current_aux = player["equipped_auxiliary_manual_id"]
        if target_primary == current_primary and target_aux == current_aux:
            return None

        if target_primary is not None and target_primary == target_aux:
            return "Manual preset skipped — saved state had the same manual in both slots."

        for manual_id in (target_primary, target_aux):
            if manual_id is None:
                continue
            manual = self.db.get_manual(manual_id)
            if manual is None or manual["owner_id"] != user_id:
                return "Manual preset skipped — you no longer own one of the saved manuals."

        remaining = self._check_cooldown(player, "last_manual_change_ts", self.MANUAL_CHANGE_COOLDOWN_SECONDS)
        if remaining > 0:
            from .ui_utils import format_duration
            return f"Manuals are still settling from your last change — try again in {format_duration(remaining)} to also restore your saved manuals."

        self.db.set_equipped_manual(user_id, "primary", target_primary)
        self.db.set_equipped_manual(user_id, "auxiliary", target_aux)
        if target_primary is not None:
            self.db.set_manual_bound(target_primary)
        if target_aux is not None:
            self.db.set_manual_bound(target_aux)
        self.db.set_timestamp_column(user_id, "last_manual_change_ts", int(time.time()))
        return "Restored your saved manuals."

    def apply_equipment_preset(self, user_id: int, name: str, preset_name: str) -> dict:
        """Re-equips everything from a saved preset: equips/swaps every slot present in the
        snapshot, empties any slot that was already empty when it was saved (a preset is a
        full loadout restore, not a merge), and restores up to 2 manuals as one combined
        change (see _apply_preset_manuals). Returns a result dict rather than a (ok, message)
        tuple since a single preset load can partially succeed (e.g. one accessory since
        salvaged) — the caller decides how to summarize applied vs. skipped slots."""
        player = self.db.get_or_create_player(user_id, name)
        preset_key, display_name = self._normalize_preset_name(preset_name)
        preset = self.db.get_equipment_preset(user_id, preset_key)
        if preset is None:
            return {"ok": False, "reason": "not_found", "display_name": display_name}

        equipped_now = self.db.get_equipped(user_id)
        equipped_gear_ids = self.db.get_equipped_gear_ids(user_id)
        equipped_accessory_ids = self.db.get_equipped_accessory_ids(user_id)

        applied = []
        skipped = []

        for slot_key in self.EQUIPMENT_PRESET_SLOT_KEYS:
            target = preset["slots"].get(slot_key)
            label = equipment.SLOT_LABEL_BY_KEY[slot_key]

            if target is None:
                if equipped_now.get(slot_key):
                    if slot_key in self.ACCESSORY_ARTIFACT_SLOT_TYPES:
                        ok, message = self.unequip_accessory_artifact(user_id, name, slot_key)
                    else:
                        ok, message = self.unequip_item(user_id, name, slot_key)
                    (applied if ok else skipped).append(message)
                continue

            if target["accessory_instance_id"] is not None:
                if equipped_accessory_ids.get(slot_key) == target["accessory_instance_id"]:
                    continue
                instance = self.db.get_accessory_instance(target["accessory_instance_id"])
                if instance is None or instance["owner_id"] != user_id:
                    skipped.append(f"{label}: no longer own **{target['item_name']}**.")
                    continue
                ok, message = self.equip_accessory_artifact(user_id, name, slot_key, target["accessory_instance_id"])
            elif target["gear_id"] is not None:
                if equipped_gear_ids.get(slot_key) == target["gear_id"]:
                    continue
                gear = self.db.get_crafted_gear(target["gear_id"])
                if gear is None or gear["owner_id"] != user_id:
                    skipped.append(f"{label}: no longer own **{target['item_name']}**.")
                    continue
                ok, message = self.equip_crafted_gear(user_id, name, target["gear_id"])
            else:
                already_this_catalog_item = (
                    equipped_now.get(slot_key) == target["item_name"]
                    and slot_key not in equipped_gear_ids and slot_key not in equipped_accessory_ids
                )
                if already_this_catalog_item:
                    continue
                if self.db.get_inventory(user_id).get(target["item_name"], 0) < 1:
                    skipped.append(f"{label}: no longer own **{target['item_name']}**.")
                    continue
                ok, message = self.equip_item(user_id, name, slot_key, target["item_name"])
            (applied if ok else skipped).append(message)

        manual_note = self._apply_preset_manuals(user_id, name, player, preset)

        return {
            "ok": True, "display_name": preset["display_name"],
            "applied": applied, "skipped": skipped, "manual_note": manual_note,
        }

    def dismantle_manual(self, user_id: int, name: str, manual_id: int):
        player = self.db.get_or_create_player(user_id, name)
        manual = self.db.get_manual(manual_id)
        if manual is None or manual["owner_id"] != user_id:
            return False, "You don't own that manual."
        if manual_id in (player["equipped_primary_manual_id"], player["equipped_auxiliary_manual_id"]):
            return False, "Unequip it first."
        if manual["rarity"] == "Unique":
            return False, "Unique manuals can't normally be dismantled."
        values = search_data.DISMANTLE_VALUES.get(manual["rarity"], {"ink": 1, "dust": 0})
        self.db.delete_manual(manual_id)
        if values["ink"]:
            self.db.add_manual_ink(user_id, values["ink"])
        dust_granted = self._grant_insight_dust(user_id, values["dust"]) if values["dust"] else 0
        return True, f"Dismantled **{manual['name']}** for {values['ink']} manual ink and {dust_granted} insight dust."

    def gamble_manual_for_page(self, user_id: int, name: str, manual_id: int, category: str) -> dict:
        """/manual's own "Gamble" button -- destroys a completed manual for a guaranteed page
        of the player's CHOSEN category, but at a rank that's rolled rather than picked (see
        manual_data.gamble_page_rank_weights, peaked at the manual's own rank). Same ownership/
        equipped/Unique guards as dismantle_manual -- a manual too valuable to casually
        dismantle is too valuable to casually gamble away either. Returns a dict:
          ok=False, reason=...
          ok=True, manual_name, page_name, page_rank, category"""
        player = self.db.get_or_create_player(user_id, name)
        manual = self.db.get_manual(manual_id)
        if manual is None or manual["owner_id"] != user_id:
            return {"ok": False, "reason": "You don't own that manual."}
        if manual_id in (player["equipped_primary_manual_id"], player["equipped_auxiliary_manual_id"]):
            return {"ok": False, "reason": "Unequip it first."}
        if manual["rarity"] == "Unique":
            return {"ok": False, "reason": "Unique manuals can't be gambled away."}
        if category not in manual_data.PAGE_CATEGORIES:
            return {"ok": False, "reason": "Not a real page category."}

        weights = manual_data.gamble_page_rank_weights(manual["rank"])
        rolled_rank = random.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]
        candidates = [p for p in manual_data.PAGES.values() if p.category == category and p.rank == rolled_rank]
        page = random.choice(candidates)

        self.db.delete_manual(manual_id)
        self.db.add_player_page(user_id, page.page_id, 1)
        return {"ok": True, "manual_name": manual["name"], "page_name": page.name, "page_rank": rolled_rank, "category": category}

    # -- Sects (see sects.py — Phase 1: core structure only, no mentor/contribution/wars/
    # buildings/missions/leaderboards yet) ----------------------------------------------

    def sect_status(self, user_id: int, name: str) -> Optional[dict]:
        """None if the player isn't in a sect. Otherwise {"sect", "members", "player_rank",
        "master", "disciples"} — the sect row, every member (rank-ordered, see
        get_sect_members), this player's own rank, their master's player row (None if they
        don't have one), and their own list of disciples — everything /sect needs to render
        in one call."""
        player = self.db.get_or_create_player(user_id, name)
        if not player["sect_id"]:
            return None
        sect = self.db.get_sect(player["sect_id"])
        if sect is None:
            # Orphaned pointer (the sect was deleted out from under them somehow) — self-heal
            # rather than leaving the player permanently stuck pointing at nothing.
            self.db.set_player_sect(user_id, None, None)
            return None
        master = self.db.get_player_row(player["master_id"]) if player["master_id"] else None
        return {
            "sect": sect, "members": self.db.get_sect_members(sect["sect_id"]), "player_rank": player["sect_rank"],
            "master": master, "disciples": self.db.get_disciples(user_id),
        }

    def personal_mentor_status(self, user_id: int, name: str) -> dict:
        """Always available regardless of sect membership (unlike sect_status) — {"master",
        "disciples"} for the personal disciple track. /sect shows this alongside the sect
        track (or on its own for a player with no sect at all)."""
        player = self.db.get_or_create_player(user_id, name)
        master = self.db.get_player_row(player["personal_master_id"]) if player["personal_master_id"] else None
        return {"master": master, "disciples": self.db.get_personal_disciples(user_id)}

    def sect_list(self) -> list:
        return self.db.list_sects()

    def sect_create(self, user_id: int, name: str, sect_name: str):
        player = self.db.get_or_create_player(user_id, name)
        if player["sect_id"]:
            return False, "You're already in a sect — leave it first via the Leave Sect button in `/sect`."
        sect_name = sect_name.strip()
        if not sect_name:
            return False, "A sect needs a real name."
        if len(sect_name) > sects.MAX_NAME_LENGTH:
            return False, f"Sect names are capped at {sects.MAX_NAME_LENGTH} characters."
        sect_id = self.db.create_sect(user_id, sect_name)
        if sect_id is None:
            return False, f"**{sect_name}** is already taken — pick a different name."
        return True, f"🏯 **{sect_name}** is founded, and you are its Sect Leader!"

    def sect_join(self, user_id: int, name: str, sect_name: str):
        """Queues a pending application rather than seating the applicant directly — see
        sect_applications table docstring / sects.can_approve_applications. A Vice Leader or
        the Sect Leader reviews it from /sect's Applications screen (sect_approve_application/
        sect_reject_application below)."""
        player = self.db.get_or_create_player(user_id, name)
        if player["sect_id"]:
            return False, "You're already in a sect — leave it first via the Leave Sect button in `/sect`."
        existing = self.db.get_pending_application_for_player(user_id)
        if existing:
            existing_sect = self.db.get_sect(existing["sect_id"])
            existing_sect_name = existing_sect["name"] if existing_sect else "a sect"
            return False, (
                f"You already have a pending application to **{existing_sect_name}** — "
                "cancel it first via the Cancel Application button in `/sect` if you'd rather apply elsewhere."
            )
        sect = self.db.get_sect_by_name(sect_name.strip())
        if sect is None:
            return False, f"No sect named **{sect_name}** exists — check `/sect_list`."
        if self.db.count_sect_members(sect["sect_id"]) >= sects.MAX_MEMBERS:
            return False, f"**{sect['name']}** is full ({sects.MAX_MEMBERS}/{sects.MAX_MEMBERS} members)."
        self.db.create_sect_application(sect["sect_id"], user_id, name)
        return True, f"🙋 Applied to **{sect['name']}** — a Vice Leader or the Sect Leader needs to accept you. Check `/sect` for status."

    def sect_cancel_application(self, user_id: int, name: str):
        self.db.get_or_create_player(user_id, name)
        application = self.db.get_pending_application_for_player(user_id)
        if not application:
            return False, "You don't have a pending sect application."
        self.db.set_application_status(application["application_id"], "cancelled", name)
        sect = self.db.get_sect(application["sect_id"])
        sect_name = sect["name"] if sect else "that sect"
        return True, f"🚫 Cancelled your application to **{sect_name}**."

    def sect_pending_applications(self, sect_id: int) -> list:
        """Permission-gating (Vice Leader+) is the caller's job — SectView already knows the
        viewer's rank before it ever shows this screen, same convention every other read-only
        display helper in this file follows."""
        return self.db.get_pending_applications_for_sect(sect_id)

    def sect_approve_application(self, user_id: int, name: str, application_id: int):
        player = self.db.get_or_create_player(user_id, name)
        if not player["sect_id"] or not sects.can_approve_applications(player["sect_rank"]):
            return False, "Only a Vice Leader or the Sect Leader can accept applications."
        application = self.db.get_sect_application(application_id)
        if not application or application["status"] != "pending" or application["sect_id"] != player["sect_id"]:
            return False, "That application is no longer pending."
        applicant = self.db.get_player_row(application["applicant_id"])
        if applicant and applicant["sect_id"]:
            self.db.set_application_status(application_id, "cancelled", name)
            return False, f"**{application['applicant_name']}** already joined another sect — application cleared."
        if self.db.count_sect_members(player["sect_id"]) >= sects.MAX_MEMBERS:
            return False, f"Your sect is full ({sects.MAX_MEMBERS}/{sects.MAX_MEMBERS}) — can't accept anyone else right now."
        self.db.set_player_sect(application["applicant_id"], player["sect_id"], sects.OUTER_DISCIPLE)
        self.db.set_application_status(application_id, "accepted", name)
        return True, f"✅ **{application['applicant_name']}** is accepted into the sect as an Outer Disciple!"

    def sect_reject_application(self, user_id: int, name: str, application_id: int):
        player = self.db.get_or_create_player(user_id, name)
        if not player["sect_id"] or not sects.can_approve_applications(player["sect_rank"]):
            return False, "Only a Vice Leader or the Sect Leader can reject applications."
        application = self.db.get_sect_application(application_id)
        if not application or application["status"] != "pending" or application["sect_id"] != player["sect_id"]:
            return False, "That application is no longer pending."
        self.db.set_application_status(application_id, "rejected", name)
        return True, f"❌ Rejected **{application['applicant_name']}**'s application."

    def sect_leave(self, user_id: int, name: str):
        player = self.db.get_or_create_player(user_id, name)
        if not player["sect_id"]:
            return False, "You're not in a sect."
        sect_id = player["sect_id"]
        sect = self.db.get_sect(sect_id)
        if player["sect_rank"] == sects.SECT_LEADER:
            if self.db.count_sect_members(sect_id) > 1:
                return False, (
                    "You're the Sect Leader — transfer leadership via the Transfer Leadership button "
                    "in `/sect` before you can leave, or the sect would be left without one."
                )
            self._release_mentor_relationships(user_id)
            self.db.set_player_sect(user_id, None, None)
            self.db.delete_pending_applications_for_sect(sect_id)
            self.db.delete_sect(sect_id)
            return True, f"You disband **{sect['name']}** as its last member and step away."
        self._release_mentor_relationships(user_id)
        self.db.set_player_sect(user_id, None, None)
        return True, f"You leave **{sect['name']}**."

    def sect_transfer_leadership(self, user_id: int, name: str, target_id: int, target_name: str):
        player = self.db.get_or_create_player(user_id, name)
        if player["sect_rank"] != sects.SECT_LEADER:
            return False, "Only the Sect Leader can transfer leadership."
        target = self.db.get_or_create_player(target_id, target_name)
        if target["sect_id"] != player["sect_id"]:
            return False, f"{target_name} isn't a member of your sect."
        if target_id == user_id:
            return False, "You're already the Sect Leader."
        self.db.set_sect_leader(player["sect_id"], target_id)
        self.db.set_sect_rank(target_id, sects.SECT_LEADER)
        self.db.set_sect_rank(user_id, sects.VICE_LEADER)
        return True, f"👑 Leadership passes to **{target_name}** — you step down to Vice Leader."

    def sect_kick(self, user_id: int, name: str, target_id: int, target_name: str):
        player = self.db.get_or_create_player(user_id, name)
        if not player["sect_id"]:
            return False, "You're not in a sect."
        if not sects.can_kick(player["sect_rank"]):
            return False, "Only the Sect Leader can kick members."
        target = self.db.get_or_create_player(target_id, target_name)
        if target["sect_id"] != player["sect_id"]:
            return False, f"{target_name} isn't a member of your sect."
        if target_id == user_id:
            return False, "You can't kick yourself — use the Leave Sect button in `/sect` instead."
        self._release_mentor_relationships(target_id)
        self.db.set_player_sect(target_id, None, None)
        return True, f"👢 **{target_name}** is expelled from the sect."

    def _release_mentor_relationships(self, user_id: int):
        """Called whenever someone leaves or is kicked from their sect — the mentor
        relationship can't survive the pair no longer sharing a sect, per the design doc's
        own "Relationship remains until... Disciple leaves sect / Master leaves sect" rule.
        Covers both directions: they stop being anyone's disciple, AND (if they were a
        master) every one of their own disciples is released too."""
        self.db.set_master(user_id, None)
        self.db.release_all_disciples(user_id)

    # -- Mentor/disciple (see sects.py's mentor section / /accept_disciple, /teach) -------

    def _validate_disciple_offer(self, master: dict, disciple: dict) -> Optional[str]:
        """Every condition an offer has to satisfy, checked both before a request is sent
        (fail fast, don't bother the target) and again right before it's actually accepted
        (in case anything changed while the request sat pending) — returns an error message,
        or None if the offer is currently valid."""
        if not master["sect_id"]:
            return "You're not in a sect."
        if not sects.can_accept_disciples(master["sect_rank"]):
            return f"You need to be an Elder or higher to take a disciple (you're a {master['sect_rank']})."
        if disciple["sect_id"] != master["sect_id"]:
            return f"{disciple['name']} isn't a member of your sect."
        if disciple["user_id"] == master["user_id"]:
            return "You can't take yourself as a disciple."
        if disciple["master_id"]:
            return f"{disciple['name']} already has a master."
        if disciple["user_id"] == master["master_id"]:
            return f"{disciple['name']} is already YOUR master — that would be circular."
        if self.db.count_disciples(master["user_id"]) >= sects.MAX_DISCIPLES_PER_MASTER:
            return f"You already have the maximum {sects.MAX_DISCIPLES_PER_MASTER} disciples."
        tenure = int(time.time()) - disciple["sect_joined_ts"]
        if tenure < sects.MIN_SECT_TENURE_BEFORE_MENTOR_SECONDS:
            remaining = sects.MIN_SECT_TENURE_BEFORE_MENTOR_SECONDS - tenure
            from .ui_utils import format_duration
            return f"{disciple['name']} needs to be in the sect a bit longer before taking a master (~{format_duration(remaining)} left)."
        return None

    def sect_can_offer_disciple(self, master_id: int, master_name: str, disciple_id: int, disciple_name: str):
        """Read-only precheck — used by /accept_disciple before it bothers pinging the
        target with a request. Returns (ok, reason_if_not)."""
        master = self.db.get_or_create_player(master_id, master_name)
        disciple = self.db.get_or_create_player(disciple_id, disciple_name)
        error = self._validate_disciple_offer(master, disciple)
        return (error is None), error

    def sect_accept_disciple(self, master_id: int, master_name: str, disciple_id: int, disciple_name: str):
        """Actually forms the relationship — called once the target accepts the request
        view. Re-validates everything sect_can_offer_disciple already checked, in case
        anything changed while the request was pending (the target got kicked, the master
        hit their cap from a different accepted offer, ...)."""
        master = self.db.get_or_create_player(master_id, master_name)
        disciple = self.db.get_or_create_player(disciple_id, disciple_name)
        error = self._validate_disciple_offer(master, disciple)
        if error:
            return False, error
        self.db.set_master(disciple_id, master_id)
        return True, f"🎓 **{disciple_name}** becomes **{master_name}**'s disciple!"

    def sect_release_disciple(self, master_id: int, master_name: str, disciple_id: int, disciple_name: str):
        master = self.db.get_or_create_player(master_id, master_name)
        disciple = self.db.get_or_create_player(disciple_id, disciple_name)
        if disciple["master_id"] != master_id:
            return False, f"{disciple_name} isn't your disciple."
        self.db.set_master(disciple_id, None)
        return True, f"**{disciple_name}** is released — they're no longer your disciple."

    def sect_leave_master(self, user_id: int, name: str):
        player = self.db.get_or_create_player(user_id, name)
        if not player["master_id"]:
            return False, "You don't have a master."
        self.db.set_master(user_id, None)
        return True, "You part ways with your master."

    def get_sect_master_info(self, user_id: int, name: str) -> Optional[dict]:
        """/sect_master's disciple-side "who is my sect master" lookup -- None if the caller
        currently has no sect master. Uses get_player_row (not get_or_create_player) for the
        MASTER's own row, since the caller here is the disciple and doesn't know the master's
        current Discord display name."""
        player = self.db.get_or_create_player(user_id, name)
        if not player["master_id"]:
            return None
        master = self.db.get_player_row(player["master_id"])
        if master is None:
            return None
        return {
            "master_name": master["name"],
            "master_realm": realms.STAGES[master["realm_index"]].display_name,
            "times_taught": player["times_taught_by_master"],
            "since_ts": player["master_since_ts"],
        }

    def _teach_disciple(self, master: dict, master_status: dict, disciple: dict, disciple_name: str) -> dict:
        """The actual lesson — shared by sect_teach_all (every sect disciple in one action)
        and personal_teach_all (every personal disciple in one action), since the Qi formula
        (see sects.py's own module docstring) doesn't change based on which track called it.
        No cap against the disciple's own next-breakthrough requirement — a master's real cultivation strength
        (and the realm-gap multiplier on top of it) is allowed to fully carry a lesson,
        including past a full breakthrough on a big enough gap. Applies the Qi grants
        directly; returns {"ok", "reason" (if not ok), "qi_granted", "master_bonus"}."""
        master_realm = realms.STAGES[master["realm_index"]].great_realm_index
        disciple_realm = realms.STAGES[disciple["realm_index"]].great_realm_index
        realm_diff = master_realm - disciple_realm
        if realm_diff < 1:
            return {"ok": False, "reason": f"{disciple_name} needs to be in a lower realm than you for a lesson to help them."}
        if realms.is_max_realm(disciple["realm_index"]):
            return {"ok": False, "reason": f"{disciple_name} is already at the peak realm — there's nothing left to teach toward."}

        multiplier = sects.realm_diff_qi_multiplier(realm_diff)
        aptitude_scale = 1 + master["aptitude"] / sects.TEACH_APTITUDE_SCALE_DIVISOR
        qi_granted = master_status["effective_rate_per_minute"] * sects.TEACH_MASTER_RATE_MINUTES * multiplier * aptitude_scale

        self.db.add_qi(disciple["user_id"], qi_granted)
        master_bonus = qi_granted * sects.TEACH_MASTER_BONUS_PCT
        self.db.add_qi(master["user_id"], master_bonus)
        return {"ok": True, "qi_granted": qi_granted, "master_bonus": master_bonus}

    def teach_all(self, user_id: int, name: str) -> dict:
        """/teach's single entry point -- merges sect_teach_all and personal_teach_all into one
        action, teaching whichever of a player's sect disciples AND personal disciples are
        currently eligible. Each side is independently SKIPPED (not a failure) if it doesn't
        apply at all (no sect, or no personal disciples) -- sect_teach_all's own "You're not in
        a sect" refusal would otherwise block a personal-only master from teaching at all, which
        this exists specifically to avoid. A side's own cooldown-gate refusal (e.g. sect still
        settling from the last lesson) IS still surfaced, just as informational content inside
        that side's own result, not a hard failure of the whole command.
        Returns {"ok", "reason" (only set if ok=False -- nothing to attempt on EITHER side),
        "sect": sect_teach_all's dict or None, "personal": personal_teach_all's dict or None}."""
        player = self.db.get_or_create_player(user_id, name)
        has_sect_disciples = bool(player["sect_id"]) and bool(self.db.get_disciples(user_id))
        has_personal_disciples = bool(self.db.get_personal_disciples(user_id))
        if not has_sect_disciples and not has_personal_disciples:
            return {"ok": False, "reason": "You don't have any disciples to teach — sect or personal.", "sect": None, "personal": None}
        sect_result = self.sect_teach_all(user_id, name) if has_sect_disciples else None
        personal_result = self.personal_teach_all(user_id, name) if has_personal_disciples else None
        return {"ok": True, "sect": sect_result, "personal": personal_result}

    def sect_teach_all(self, master_id: int, master_name: str) -> dict:
        """Teaching transfers Qi to every current sect disciple at once (was one-disciple-per-
        use; changed to hit the whole roster in a single action per explicit request) — it
        never costs the master their own banked Qi (see sects.py's own module docstring for
        the formula). Also grants the master a small cultivation gain of their own per
        disciple taught, the one benefit from the doc's "Master Benefits" list this codebase
        can implement without a contribution/merit/reputation system that doesn't exist yet.
        Keeps the ORIGINAL single master-level cooldown (database.players.last_teach_ts,
        sects.TEACH_COOLDOWN_SECONDS) rather than switching to personal_teach_all's
        per-disciple clocks — one shared gate for the whole batch action, only burned if at
        least one disciple was actually taught (mirrors this method's own former all-or-
        nothing behavior: a single failed lesson never used to cost the cooldown either).
        Returns {"ok", "reason" (if not ok, e.g. no sect/no disciples/still on cooldown),
        "taught": [...], "beyond_instruction": [...]}."""
        master = self.db.get_or_create_player(master_id, master_name)
        if not master["sect_id"]:
            return {"ok": False, "reason": "You're not in a sect."}
        disciples = self.db.get_disciples(master_id)
        if not disciples:
            return {"ok": False, "reason": "You don't have any disciples yet — an Elder+ can take some on with `/accept_disciple`."}
        remaining = self._check_cooldown(master, "last_teach_ts", sects.TEACH_COOLDOWN_SECONDS)
        if remaining > 0:
            from .ui_utils import format_duration
            return {"ok": False, "reason": f"You're still settling from your last lesson — try again in {format_duration(remaining)}."}

        master_status = self.get_qi_status(master_id, master_name)
        taught, beyond_instruction = [], []
        for row in disciples:
            result = self._teach_disciple(master, master_status, row, row["name"])
            if not result["ok"]:
                beyond_instruction.append({"name": row["name"], "reason": result["reason"]})
                continue
            self.db.increment_times_taught_by_master(row["user_id"])
            taught.append({"name": row["name"], "qi_granted": result["qi_granted"], "master_bonus": result["master_bonus"]})
        if taught:
            self.db.set_last_teach_ts(master_id, int(time.time()))
        return {"ok": True, "taught": taught, "beyond_instruction": beyond_instruction}

    # -- Personal disciples (no sect required — see sects.py's own module docstring) ------

    def _validate_personal_offer(self, master: dict, disciple: dict) -> Optional[str]:
        if disciple["user_id"] == master["user_id"]:
            return "You can't take yourself as a disciple."
        if disciple["personal_master_id"]:
            return f"{disciple['name']} already has a personal master."
        if disciple["user_id"] == master["personal_master_id"]:
            return f"{disciple['name']} is already YOUR personal master — that would be circular."
        if self.db.count_personal_disciples(master["user_id"]) >= sects.MAX_PERSONAL_DISCIPLES:
            return f"You already have the maximum {sects.MAX_PERSONAL_DISCIPLES} personal disciples."
        return None

    def personal_can_offer_disciple(self, master_id: int, master_name: str, disciple_id: int, disciple_name: str):
        master = self.db.get_or_create_player(master_id, master_name)
        disciple = self.db.get_or_create_player(disciple_id, disciple_name)
        error = self._validate_personal_offer(master, disciple)
        return (error is None), error

    def personal_accept_disciple(self, master_id: int, master_name: str, disciple_id: int, disciple_name: str):
        master = self.db.get_or_create_player(master_id, master_name)
        disciple = self.db.get_or_create_player(disciple_id, disciple_name)
        error = self._validate_personal_offer(master, disciple)
        if error:
            return False, error
        self.db.set_personal_master(disciple_id, master_id)
        return True, f"🎓 **{disciple_name}** becomes **{master_name}**'s personal disciple!"

    def personal_release_disciple(self, master_id: int, master_name: str, disciple_id: int, disciple_name: str):
        master = self.db.get_or_create_player(master_id, master_name)
        disciple = self.db.get_or_create_player(disciple_id, disciple_name)
        if disciple["personal_master_id"] != master_id:
            return False, f"{disciple_name} isn't your personal disciple."
        self.db.set_personal_master(disciple_id, None)
        return True, f"**{disciple_name}** is released — they're no longer your personal disciple."

    def personal_leave_master(self, user_id: int, name: str):
        player = self.db.get_or_create_player(user_id, name)
        if not player["personal_master_id"]:
            return False, "You don't have a personal master."
        self.db.set_personal_master(user_id, None)
        return True, "You part ways with your personal master."

    def get_personal_master_info(self, user_id: int, name: str) -> Optional[dict]:
        """/master's disciple-side lookup -- personal-track sibling of get_sect_master_info."""
        player = self.db.get_or_create_player(user_id, name)
        if not player["personal_master_id"]:
            return None
        master = self.db.get_player_row(player["personal_master_id"])
        if master is None:
            return None
        return {
            "master_name": master["name"],
            "master_realm": realms.STAGES[master["realm_index"]].display_name,
            "times_taught": player["personal_times_taught"],
            "since_ts": player["personal_master_since_ts"],
        }

    def personal_teach_all(self, master_id: int, master_name: str) -> dict:
        """The personal-track equivalent of sect_teach_all — also one action against the
        whole roster, but unlike sect_teach_all's single master-level cooldown, each
        disciple carries their OWN clock (database.players.personal_last_taught_ts) so the
        roster doesn't share one gate — running this just teaches whoever is currently off
        cooldown and reports the rest, rather than blocking the whole action until the
        slowest disciple's timer clears. Each disciple still gets the exact same Qi formula
        sect_teach_all uses (see _teach_disciple) — a lower cap and no sect/rank gate don't
        mean weaker guardrails on the lesson itself.

        Returns {"ok", "reason" (if not ok, e.g. no disciples at all), "taught": [...],
        "on_cooldown": [...], "beyond_instruction": [...]} — always "ok" once there's a
        roster to check, even if every disciple ends up skipped, since there's no shared
        cooldown left to "burn" on a no-op run."""
        master = self.db.get_or_create_player(master_id, master_name)
        disciples = self.db.get_personal_disciples(master_id)
        if not disciples:
            return {"ok": False, "reason": "You don't have any personal disciples yet — try `/master_offer`."}

        # The cooldown-reduction bonus (manual effects) is the MASTER's own — they're the one
        # teaching faster — even though the timestamp being checked lives on each disciple.
        reduction = self.compute_equipment_bonuses(master_id).get("cooldown_reduction_pct", 0)
        effective_cooldown = round(sects.PERSONAL_TEACH_COOLDOWN_SECONDS * (1 - min(0.9, max(0.0, reduction))))

        master_status = self.get_qi_status(master_id, master_name)
        now = int(time.time())
        taught, on_cooldown, beyond_instruction = [], [], []
        for row in disciples:
            remaining = max(0, effective_cooldown - (now - row["personal_last_taught_ts"]))
            if remaining > 0:
                on_cooldown.append({"name": row["name"], "remaining": remaining})
                continue
            result = self._teach_disciple(master, master_status, row, row["name"])
            if not result["ok"]:
                beyond_instruction.append({"name": row["name"], "reason": result["reason"]})
                continue
            self.db.set_personal_last_taught_ts(row["user_id"], now)
            self.db.increment_personal_times_taught(row["user_id"])
            taught.append({"name": row["name"], "qi_granted": result["qi_granted"], "master_bonus": result["master_bonus"]})

        return {"ok": True, "taught": taught, "on_cooldown": on_cooldown, "beyond_instruction": beyond_instruction}

    # -- Dao Companion (see game/dao_companion.py / /offer_companion, /companion -- the
    # latter's own Daily Burst/Break Bond buttons absorbed the old standalone /dc and
    # /break_companion commands, retired 2026-08-14 to free guild slash-command slots) -- a
    # mutual, symmetric peer bond, unlike the mentor/disciple hierarchy above: both partners
    # gain a slice of the OTHER's raw stats (grows with bond duration), and either can
    # trigger a once-daily qi burst that pays out to both sides. ---------------------------

    def _validate_dao_companion_offer(self, offerer: dict, target: dict) -> Optional[str]:
        """Checked both before a request is sent (fail fast) and again right before it's
        accepted (state may have changed while it sat pending) -- returns an error message,
        or None if the offer is currently valid."""
        if offerer["user_id"] == target["user_id"]:
            return "You can't bond with yourself."
        if not target["character_confirmed"]:
            return f"{target['name']} hasn't started their cultivation journey yet."
        if self.db.get_dao_companion(offerer["user_id"]):
            return "You already have a Dao Companion — use `/companion`'s Break Bond button first if you want to bond with someone else."
        if self.db.get_dao_companion(target["user_id"]):
            return f"{target['name']} already has a Dao Companion."
        return None

    def dao_companion_can_offer(self, offerer_id: int, offerer_name: str, target_id: int, target_name: str):
        """Read-only precheck -- used by /offer_companion before it bothers pinging the
        target with a request. Returns (ok, reason_if_not)."""
        offerer = self.db.get_or_create_player(offerer_id, offerer_name)
        target = self.db.get_or_create_player(target_id, target_name)
        error = self._validate_dao_companion_offer(offerer, target)
        return (error is None), error

    def dao_companion_accept(self, offerer_id: int, offerer_name: str, target_id: int, target_name: str):
        """Actually forms the bond -- called once the target accepts the request view.
        Re-validates everything dao_companion_can_offer already checked, in case anything
        changed while the request was pending (either side bonded with someone else, ...)."""
        offerer = self.db.get_or_create_player(offerer_id, offerer_name)
        target = self.db.get_or_create_player(target_id, target_name)
        error = self._validate_dao_companion_offer(offerer, target)
        if error:
            return False, error
        self.db.create_dao_companion(offerer_id, target_id, int(time.time()))
        return True, f"💞 **{offerer_name}** and **{target_name}** become Dao Companions!"

    def dao_companion_break(self, user_id: int, name: str):
        player = self.db.get_or_create_player(user_id, name)
        companion = self.db.get_dao_companion(user_id)
        if companion is None:
            return False, "You don't have a Dao Companion."
        partner_id = companion["partner_b_id"] if companion["partner_a_id"] == player["user_id"] else companion["partner_a_id"]
        partner = self.db.get_player_row(partner_id)
        partner_name = partner["name"] if partner else "your former companion"
        self.db.delete_dao_companion(companion["id"])
        return True, f"You and **{partner_name}** are no longer Dao Companions."

    def _dao_companion_partner_id(self, companion: dict, user_id: int) -> int:
        return companion["partner_b_id"] if companion["partner_a_id"] == user_id else companion["partner_a_id"]

    def get_dao_companion_status(self, user_id: int, name: str) -> Optional[dict]:
        """/companion's read-only lookup -- None if the player has no companion right now."""
        self.db.get_or_create_player(user_id, name)
        companion = self.db.get_dao_companion(user_id)
        if companion is None:
            return None
        partner_id = self._dao_companion_partner_id(companion, user_id)
        partner_row = self.db.get_player_row(partner_id)
        bonded_seconds = int(time.time()) - companion["formed_ts"]
        share_pct = dao_companion.stat_share_pct(bonded_seconds)
        stat_bonuses = {stat: (partner_row[stat] if partner_row else 0) * share_pct for stat in dao_companion.DAO_COMPANION_SHARED_STATS}
        return {
            "partner_name": partner_row["name"] if partner_row else "Unknown",
            "formed_ts": companion["formed_ts"],
            "times_used": companion["times_used"],
            "total_qi_granted": companion["total_qi_granted"],
            "stat_share_pct": share_pct,
            "stat_bonuses": stat_bonuses,
        }

    def get_dao_companion_stat_bonus(self, user_id: int) -> dict:
        """Feeds compute_equipment_bonuses -- {} if no companion, else the partner's raw
        stats x the current bond-duration-scaled share (see dao_companion.stat_share_pct)."""
        companion = self.db.get_dao_companion(user_id)
        if companion is None:
            return {}
        partner_id = self._dao_companion_partner_id(companion, user_id)
        partner_row = self.db.get_player_row(partner_id)
        if partner_row is None:
            return {}
        share_pct = dao_companion.stat_share_pct(int(time.time()) - companion["formed_ts"])
        return {stat: partner_row[stat] * share_pct for stat in dao_companion.DAO_COMPANION_SHARED_STATS}

    def dao_companion_burst(self, user_id: int, name: str) -> dict:
        """"i dc" -- once per day, per player (either partner can trigger it), grants BOTH
        partners a qi burst sized off their OWN qi rate (no aptitude/realm scaling like
        /teach's formula -- this is a peer bond, not a mentorship). Returns {"ok": False,
        "reason"} or {"ok": True, "partner_name", "qi_to_caller", "qi_to_partner"}."""
        player = self.db.get_or_create_player(user_id, name)
        companion = self.db.get_dao_companion(user_id)
        if companion is None:
            return {"ok": False, "reason": "You don't have a Dao Companion yet — use `/offer_companion` to bond with someone."}
        remaining = self._check_cooldown(player, "last_dc_burst_ts", dao_companion.DAO_COMPANION_BURST_COOLDOWN_SECONDS)
        if remaining > 0:
            from .ui_utils import format_duration
            return {"ok": False, "reason": f"You're still settling from your last burst — try again in {format_duration(remaining)}.", "remaining_seconds": remaining}

        partner_id = self._dao_companion_partner_id(companion, user_id)
        partner_row = self.db.get_player_row(partner_id)
        partner_name = partner_row["name"] if partner_row else "your companion"

        caller_rate = self.get_qi_status(user_id, name)["effective_rate_per_minute"]
        qi_to_caller = caller_rate * dao_companion.DAO_COMPANION_BURST_RATE_MINUTES
        self.db.add_qi(user_id, qi_to_caller)

        qi_to_partner = 0.0
        if partner_row is not None:
            partner_rate = self.db.get_qi_status(partner_id)["effective_rate_per_minute"]
            qi_to_partner = partner_rate * dao_companion.DAO_COMPANION_BURST_RATE_MINUTES
            self.db.add_qi(partner_id, qi_to_partner)

        self.db.record_dao_companion_burst(companion["id"], qi_to_caller + qi_to_partner)
        self.db.set_timestamp_column(user_id, "last_dc_burst_ts", int(time.time()))
        return {"ok": True, "partner_name": partner_name, "qi_to_caller": qi_to_caller, "qi_to_partner": qi_to_partner}

    # -- Essence Exchange (see /essence_exchange) -- unlike "i dc"'s instant/unilateral burst
    # above, this is a mutual CONFIRMED action: the partner has ESSENCE_EXCHANGE_TIMEOUT_SECONDS
    # to accept before it expires. A real DB-backed request + periodic sweep (not a pure
    # in-memory View timeout like DaoCompanionRequestView's own 5-minute offer window) --
    # 3 hours is far more likely to overlap a redeploy than 5 minutes, and this codebase
    # already learned that exact lesson once from a live trade-timeout incident. Cooldown
    # lives on the companion bond itself (last_essence_exchange_ts), not a per-player column,
    # since it's a shared once-per-day-per-PAIR action regardless of who initiates -- deliberately
    # flat (no cooldown_reduction_pct gear discount, unlike _check_cooldown's usual player-column
    # model), since it's not clear whose gear would even apply to a joint pair action.

    ESSENCE_EXCHANGE_TIMEOUT_SECONDS = 3 * 3600
    ESSENCE_EXCHANGE_COOLDOWN_SECONDS = 24 * 3600
    ESSENCE_EXCHANGE_PERCENT = 0.33

    def essence_exchange_propose(self, user_id: int, name: str) -> dict:
        self.db.get_or_create_player(user_id, name)
        companion = self.db.get_dao_companion(user_id)
        if companion is None:
            return {"ok": False, "reason": "You don't have a Dao Companion yet — use `/offer_companion` to bond with someone."}
        remaining = max(0, self.ESSENCE_EXCHANGE_COOLDOWN_SECONDS - (int(time.time()) - companion["last_essence_exchange_ts"]))
        if remaining > 0:
            from .ui_utils import format_duration
            return {"ok": False, "reason": f"You and your companion already exchanged essence recently — try again in {format_duration(remaining)}.", "remaining_seconds": remaining}
        if self.db.get_pending_essence_exchange_for_companion(companion["id"]):
            return {"ok": False, "reason": "There's already a pending Essence Exchange request with your companion."}
        partner_id = self._dao_companion_partner_id(companion, user_id)
        partner_row = self.db.get_player_row(partner_id)
        partner_name = partner_row["name"] if partner_row else "your companion"
        request_id = self.db.create_essence_exchange_request(companion["id"], user_id, partner_id, int(time.time()))
        return {"ok": True, "request_id": request_id, "companion_id": companion["id"], "partner_id": partner_id, "partner_name": partner_name}

    def essence_exchange_accept(self, request_id: int, accepter_id: int) -> dict:
        """Called once the partner accepts the request view. Re-validates everything fresh
        (request still pending/not expired, accepter really is the invited partner, the bond
        itself hasn't ended) in case anything changed while the request sat waiting -- same
        re-validate-on-accept discipline dao_companion_accept already uses."""
        request = self.db.get_essence_exchange_request(request_id)
        if request is None:
            return {"ok": False, "reason": "That Essence Exchange request no longer exists."}
        if request["status"] != "pending":
            return {"ok": False, "reason": f"That Essence Exchange request has already been {request['status']}."}
        if accepter_id != request["partner_id"]:
            return {"ok": False, "reason": "Only the invited companion can accept this."}
        if int(time.time()) - request["created_ts"] > self.ESSENCE_EXCHANGE_TIMEOUT_SECONDS:
            self.db.set_essence_exchange_status(request_id, "expired")
            return {"ok": False, "reason": "This Essence Exchange request has expired."}
        companion = self.db.get_dao_companion(request["proposer_id"])
        if companion is None or companion["id"] != request["companion_id"]:
            self.db.set_essence_exchange_status(request_id, "declined")
            return {"ok": False, "reason": "That Dao Companion bond has ended — this request is no longer valid."}

        proposer_id, partner_id = request["proposer_id"], request["partner_id"]
        proposer_restored, proposer_essence, proposer_max = self.db.restore_essence_percent(proposer_id, self.ESSENCE_EXCHANGE_PERCENT)
        partner_restored, partner_essence, partner_max = self.db.restore_essence_percent(partner_id, self.ESSENCE_EXCHANGE_PERCENT)
        self.db.set_dao_companion_essence_exchange_ts(companion["id"], int(time.time()))
        self.db.set_essence_exchange_status(request_id, "accepted")
        proposer_row = self.db.get_player_row(proposer_id)
        partner_row = self.db.get_player_row(partner_id)
        return {
            "ok": True,
            "proposer_name": proposer_row["name"] if proposer_row else "?",
            "partner_name": partner_row["name"] if partner_row else "?",
            "proposer_restored": proposer_restored, "proposer_essence": proposer_essence, "proposer_max": proposer_max,
            "partner_restored": partner_restored, "partner_essence": partner_essence, "partner_max": partner_max,
        }

    def essence_exchange_decline(self, request_id: int, user_id: int) -> dict:
        request = self.db.get_essence_exchange_request(request_id)
        if request is None:
            return {"ok": False, "reason": "That Essence Exchange request no longer exists."}
        if request["status"] != "pending":
            return {"ok": False, "reason": f"That Essence Exchange request has already been {request['status']}."}
        if user_id not in (request["proposer_id"], request["partner_id"]):
            return {"ok": False, "reason": "This isn't your Essence Exchange request."}
        self.db.set_essence_exchange_status(request_id, "declined")
        return {"ok": True}

    def expire_stale_essence_exchanges(self) -> list:
        """Cancels every Essence Exchange request past ESSENCE_EXCHANGE_TIMEOUT_SECONDS with
        no resolution. Returns the list of expired request rows so the caller can DM both
        sides -- see GameCog.essence_exchange_timeout_tick. Mirrors expire_stale_trades'
        own shape exactly."""
        cutoff = int(time.time()) - self.ESSENCE_EXCHANGE_TIMEOUT_SECONDS
        stale = self.db.get_stale_essence_exchange_requests(cutoff)
        for request in stale:
            self.db.set_essence_exchange_status(request["id"], "expired")
        return stale

    def sect_promote(self, user_id: int, name: str, target_id: int, target_name: str):
        player = self.db.get_or_create_player(user_id, name)
        if not player["sect_id"]:
            return False, "You're not in a sect."
        target = self.db.get_or_create_player(target_id, target_name)
        if target["sect_id"] != player["sect_id"]:
            return False, f"{target_name} isn't a member of your sect."
        if target_id == user_id:
            return False, "You can't promote yourself."
        current_idx = sects.rank_index(target["sect_rank"])
        if current_idx >= sects.rank_index(sects.SECT_LEADER) - 1:
            return False, f"**{target_name}** is already a Vice Leader — use the Transfer Leadership button in `/sect` to hand off leadership instead."
        next_rank = sects.SECT_RANKS[current_idx + 1]
        if next_rank not in sects.promotable_target_ranks(player["sect_rank"]):
            return False, f"Your rank ({player['sect_rank']}) can't promote members to {next_rank}."
        if next_rank == sects.ELDER and self.db.count_sect_rank(player["sect_id"], sects.ELDER) >= sects.MAX_ELDERS:
            return False, f"The sect already has the maximum {sects.MAX_ELDERS} Elders."
        if next_rank == sects.VICE_LEADER and self.db.count_sect_rank(player["sect_id"], sects.VICE_LEADER) >= sects.MAX_VICE_LEADERS:
            return False, f"The sect already has the maximum {sects.MAX_VICE_LEADERS} Vice Leaders."
        self.db.set_sect_rank(target_id, next_rank)
        return True, f"⬆️ **{target_name}** is promoted to {sects.RANK_EMOJI[next_rank]} {next_rank}!"

    def sect_demote(self, user_id: int, name: str, target_id: int, target_name: str):
        player = self.db.get_or_create_player(user_id, name)
        if not player["sect_id"]:
            return False, "You're not in a sect."
        if not sects.can_demote(player["sect_rank"]):
            return False, "Only the Sect Leader or a Vice Leader can demote members."
        target = self.db.get_or_create_player(target_id, target_name)
        if target["sect_id"] != player["sect_id"]:
            return False, f"{target_name} isn't a member of your sect."
        if target_id == user_id:
            return False, "You can't demote yourself — use the Transfer Leadership button in `/sect` if you want to step down."
        current_idx = sects.rank_index(target["sect_rank"])
        if current_idx <= 0:
            return False, f"**{target_name}** is already an Outer Disciple — use the Kick button in `/sect` to remove them instead."
        if target["sect_rank"] not in sects.demotable_target_ranks(player["sect_rank"]):
            return False, f"Your rank ({player['sect_rank']}) can't demote a {target['sect_rank']}."
        prev_rank = sects.SECT_RANKS[current_idx - 1]
        self.db.set_sect_rank(target_id, prev_rank)
        return True, f"⬇️ **{target_name}** is demoted to {sects.RANK_EMOJI[prev_rank]} {prev_rank}."

    def sect_donate(self, user_id: int, name: str, amount: int):
        player = self.db.get_or_create_player(user_id, name)
        if not player["sect_id"]:
            return False, "You're not in a sect."
        if amount < 1:
            return False, "Donate at least 1 spirit stone."
        if not self.db.spend_spirit_stones(user_id, amount):
            return False, f"You don't have {format_number(amount)} spirit stones to donate."
        self.db.add_sect_treasury(player["sect_id"], amount)
        sect = self.db.get_sect(player["sect_id"])
        return True, f"💰 You donate **{format_number(amount)}** spirit stones — the treasury now holds {format_number(sect['treasury_spirit_stones'])}."

    def sect_withdraw(self, user_id: int, name: str, amount: int):
        player = self.db.get_or_create_player(user_id, name)
        if not player["sect_id"]:
            return False, "You're not in a sect."
        if not sects.can_withdraw_treasury(player["sect_rank"]):
            return False, "Only the Sect Leader or a Vice Leader can withdraw from the treasury."
        if amount < 1:
            return False, "Withdraw at least 1 spirit stone."
        if not self.db.spend_sect_treasury(player["sect_id"], amount):
            sect = self.db.get_sect(player["sect_id"])
            return False, f"The treasury only holds {format_number(sect['treasury_spirit_stones'])} spirit stones."
        self.db.add_spirit_stones(user_id, amount)
        return True, f"💰 You withdraw **{format_number(amount)}** spirit stones from the treasury."

    def sect_set_motto(self, user_id: int, name: str, motto: str):
        player = self.db.get_or_create_player(user_id, name)
        if not player["sect_id"]:
            return False, "You're not in a sect."
        if not sects.can_edit_sect_info(player["sect_rank"]):
            return False, "Only the Sect Leader can set the sect's motto."
        motto = motto.strip()
        if len(motto) > sects.MAX_MOTTO_LENGTH:
            return False, f"Mottos are capped at {sects.MAX_MOTTO_LENGTH} characters."
        self.db.set_sect_motto(player["sect_id"], motto)
        return True, f"📜 The sect's motto is now: *{motto}*" if motto else "📜 The sect's motto is cleared."

    def sect_set_banner(self, user_id: int, name: str, banner: str):
        player = self.db.get_or_create_player(user_id, name)
        if not player["sect_id"]:
            return False, "You're not in a sect."
        if not sects.can_edit_sect_info(player["sect_rank"]):
            return False, "Only the Sect Leader can set the sect's banner."
        banner = banner.strip()
        if not banner or len(banner) > sects.MAX_BANNER_LENGTH:
            return False, f"Pick a single emoji for the banner (max {sects.MAX_BANNER_LENGTH} characters)."
        self.db.set_sect_banner(player["sect_id"], banner)
        return True, f"🎌 The sect's banner is now {banner}."

    def sect_rename(self, user_id: int, name: str, new_name: str):
        player = self.db.get_or_create_player(user_id, name)
        if not player["sect_id"]:
            return False, "You're not in a sect."
        if not sects.can_edit_sect_info(player["sect_rank"]):
            return False, "Only the Sect Leader can rename the sect."
        new_name = new_name.strip()
        if not new_name:
            return False, "A sect needs a real name."
        if len(new_name) > sects.MAX_NAME_LENGTH:
            return False, f"Sect names are capped at {sects.MAX_NAME_LENGTH} characters."
        if not self.db.rename_sect(player["sect_id"], new_name):
            return False, f"**{new_name}** is already taken — pick a different name."
        return True, f"🏯 The sect is renamed to **{new_name}**."

    # -- World Boss (see world_boss.py's own module docstring / /raidboss) -----------------

    # Battle Intent Gu: +3% World Boss damage per prior consecutive hit THIS player has
    # already landed on the current boss, capped so a long grinding streak doesn't spiral.
    WORLD_BOSS_BATTLE_INTENT_PCT_PER_ATTACK = 0.03
    WORLD_BOSS_BATTLE_INTENT_MAX_PCT = 0.60

    # Nascent Soul Avatar gear's "commonly" drop source (see game/avatar_gear.py) — every
    # contributor gets an independent roll at boss end, not just the one lottery winner.
    # History: 0.30 -> 0.60 (moved "the big loot increase" here from raid boss) -> 0.85
    # (bumped further per explicit "should feel good to kill one" follow-up).
    WORLD_BOSS_AVATAR_GEAR_CHANCE = 0.85

    def get_world_boss_status(self) -> dict:
        """Read-only snapshot for /raidboss -- settles an overdue-but-still-marked-alive
        boss first (see maybe_spawn_world_boss), so status never shows stale "0 HP but still
        alive" or "expired 6 hours ago" state."""
        self.maybe_spawn_world_boss()
        active = self.db.get_active_world_boss()
        if active:
            return {"active": True, "boss": active, "roster": world_boss.WORLD_BOSSES[active["boss_key"]]}
        latest = self.db.get_latest_world_boss()
        remaining = 0
        if latest and latest["ended_ts"]:
            remaining = max(0, latest["ended_ts"] + world_boss.WORLD_BOSS_RESPAWN_DELAY_SECONDS - int(time.time()))
        return {"active": False, "boss": None, "next_spawn_remaining": remaining}

    def maybe_spawn_world_boss(self, force: bool = False) -> Optional[dict]:
        """Called opportunistically (every /raidboss status/attack, plus the background
        world_boss_tick task loop in cog.py) -- expires an overdue active boss first, then
        spawns a fresh random one if none is active and the 3h respawn delay has passed.
        force=True (the /raidboss_spawn admin override) skips the delay and ends whatever's
        currently active first. Returns the newly spawned boss row, or None if nothing
        changed this call."""
        active = self.db.get_active_world_boss()
        now = int(time.time())
        if active and active["expires_ts"] and active["expires_ts"] <= now:
            self._end_world_boss(active["boss_instance_id"], "expired")
            active = None
        if active:
            if not force:
                return None
            self._end_world_boss(active["boss_instance_id"], "force_ended")
        elif not force:
            latest = self.db.get_latest_world_boss()
            if latest and latest["ended_ts"] and now - latest["ended_ts"] < world_boss.WORLD_BOSS_RESPAWN_DELAY_SECONDS:
                return None

        boss_key = world_boss.roll_boss_key()
        expires_ts = now + world_boss.WORLD_BOSS_LIFETIME_SECONDS
        boss_instance_id = self.db.create_world_boss(boss_key, world_boss.WORLD_BOSS_MAX_HP, expires_ts)
        return self.db.get_world_boss(boss_instance_id)

    def _resolve_world_boss_reward(self, user_id: int, name: str, boss_key: str, reward: dict) -> str:
        """Turns one world_boss.roll_world_boss_loot result into an actually-granted reward
        and its display text -- handles the two sentinel kinds that module deliberately can't
        resolve itself (no GameManager access): "boss_exclusive" (one of THIS boss's own
        roster.exclusive_pool items) and "accessory_roll" (a real accessory/artifact via the
        normal roll_and_grant_accessory_artifact pipeline, rank 7 -- a world boss is
        endgame-scale, not tied to any one player's own realm)."""
        kind = reward.get("kind")
        if kind == "boss_exclusive":
            exclusive_name = random.choice(world_boss.WORLD_BOSSES[boss_key]["exclusive_pool"])
            return self.grant_reward(user_id, name, {"kind": "item", "item_name": exclusive_name, "quantity": 1})
        if kind == "accessory_roll":
            grant = self.roll_and_grant_accessory_artifact(user_id, name, "world_boss", 7, [])
            if grant:
                return f"**{grant['affix'].name}**"
            return self.grant_reward(user_id, name, {"kind": "stones", "amount": 500})
        return self.grant_reward(user_id, name, reward)

    def _end_world_boss(self, boss_instance_id: int, status: str) -> dict:
        """Distributes rewards on defeat, natural expiry, or an admin force-end alike (the
        doc's own "Boss remains alive until defeated or until its timer expires" implies
        rewards happen either way) -- guaranteed stones scaled by each contributor's % of
        total damage (see world_boss.guaranteed_reward_stones), plus
        world_boss.WORLD_BOSS_LOTTERY_ROLL_COUNT independent damage-weighted lottery picks
        (the doc's own "ticket" formula, see world_boss.weighted_lottery_winner) each for
        their own bonus item roll. Marks the boss row's status either way. Returns a summary
        dict for the caller (e.g. the /raidboss attack response, or the spawn-loop
        announcement) to report.

        2026-08-21 rework ("worth it for people to attack based on rankings"): contributors is
        already damage-sorted DESC (see GameDatabase.get_world_boss_contributors), so each
        contributor's list POSITION is their real placement -- world_boss.contribution_rank_tier
        turns that into a tier (top1/top3/top10/participant) that scales the 3 rare-roll
        mechanics (extra independent rolls -- hits stack, they don't just replace the baseline
        one), the avatar-gear chance, and a brand-new bonus loot-band roll on top of the
        unchanged lottery below."""
        boss = self.db.get_world_boss(boss_instance_id)
        contributors = self.db.get_world_boss_contributors(boss_instance_id)
        total_damage = sum(c["damage_dealt"] for c in contributors)

        guaranteed_summaries = []
        for rank, c in enumerate(contributors, start=1):
            tier = world_boss.contribution_rank_tier(rank)
            extra_rolls = world_boss.EXTRA_RARE_ROLLS_BY_TIER[tier]
            stones = world_boss.guaranteed_reward_stones(c["damage_dealt"], total_damage)
            if stones > 0:
                self.db.add_spirit_stones(c["user_id"], stones)
            # Essence Restoration Pill: rare bonus roll for every contributor (1 baseline +
            # extra_rolls for a top rank), independent of the lottery draw below (see items.
            # roll_essence_restoration_pill_drop's own docstring for why this pill moved here
            # instead of the Alchemist craft table). Every hit across the extra rolls stacks.
            essence_pills = []
            for _ in range(1 + extra_rolls):
                hit = roll_essence_restoration_pill_drop()
                if hit:
                    essence_pills.append(hit)
                    self.db.add_item(c["user_id"], hit[0], hit[1])
            # Qi Ascension Pill: same "1 baseline + extra_rolls for a top rank" shape as the
            # Essence Restoration Pill roll just above, one of only three drop sources for
            # this pill (the other two are /search_forgotten_blessed_land and /explore -- see
            # items.roll_qi_ascension_pill_drop's own docstring for why it's this narrow).
            qi_ascension_pills = []
            for _ in range(1 + extra_rolls):
                hit = items.roll_qi_ascension_pill_drop()
                if hit:
                    qi_ascension_pills.append(hit)
                    self.db.add_item(c["user_id"], hit[0], hit[1])
            # Nascent Soul Avatar gear (see game/avatar_gear.py) — World Boss is this
            # system's "commonly" source (every contributor gets an independent roll, unlike
            # the single damage-weighted lottery winner below), gated on the avatar being
            # unlocked at all so a sub-Nascent-Soul contributor never rolls for gear they
            # can't use. Chance now scales by rank tier (world_boss.AVATAR_GEAR_CHANCE_BY_TIER)
            # instead of the old flat WORLD_BOSS_AVATAR_GEAR_CHANCE for everyone -- gear's own
            # TIER stays fixed at avatar_gear.MAX_TIER regardless of rank (nothing higher to give).
            avatar_gear_grant = None
            if self.is_avatar_unlocked(c["user_id"], c["name"]) and random.random() < world_boss.AVATAR_GEAR_CHANCE_BY_TIER[tier]:
                avatar_gear_grant = self.roll_and_grant_avatar_gear(c["user_id"], c["name"], "world_boss", avatar_gear.MAX_TIER)
            # Manual page: rare bonus roll for every contributor (see world_boss.
            # roll_manual_page_rank's own docstring for the exact odds), same "1 baseline +
            # extra_rolls" shape as the pill rolls above -- every hit stacks.
            manual_pages = []
            for _ in range(1 + extra_rolls):
                page_rank = world_boss.roll_manual_page_rank()
                if page_rank is not None:
                    page = random.choice([p for p in manual_data.PAGES.values() if p.rank == page_rank])
                    self.db.add_player_page(c["user_id"], page.page_id, 1)
                    manual_pages.append({"rank": page_rank, "name": page.name})
            # Bonus loot-band roll (world_boss.BONUS_LOOT_ROLL_CHANCE_BY_TIER) -- an extra,
            # independent shot at the SAME 5-tier band table the damage-weighted lottery below
            # draws from, gated purely on RANK rather than damage-weighted luck. #1 always gets
            # one; a plain participant never does (their own shot at this pool is still the
            # lottery, unchanged).
            bonus_loot_text = None
            if random.random() < world_boss.BONUS_LOOT_ROLL_CHANCE_BY_TIER[tier]:
                contribution_scale = (c["damage_dealt"] / total_damage) if total_damage else 0
                bonus_reward = world_boss.roll_world_boss_loot(boss["boss_key"], contribution_scale)
                bonus_loot_text = self._resolve_world_boss_reward(c["user_id"], c["name"], boss["boss_key"], bonus_reward)
            self.db.mark_world_boss_contributor_rewarded(boss_instance_id, c["user_id"])
            guaranteed_summaries.append({
                "user_id": c["user_id"], "name": c["name"], "damage_dealt": c["damage_dealt"],
                "rank": rank, "tier": tier,
                "stones": stones, "essence_pills": essence_pills, "qi_ascension_pills": qi_ascension_pills,
                "avatar_gear": avatar_gear_grant, "manual_pages": manual_pages, "bonus_loot_text": bonus_loot_text,
            })

        contribution_map = {c["user_id"]: c["damage_dealt"] for c in contributors}
        lottery_winners = []
        for _ in range(world_boss.WORLD_BOSS_LOTTERY_ROLL_COUNT):
            winner_id = world_boss.weighted_lottery_winner(contribution_map)
            if winner_id is None:
                break  # nobody dealt damage -- every further roll would be empty too
            winner_row = next(c for c in contributors if c["user_id"] == winner_id)
            contribution_scale = (winner_row["damage_dealt"] / total_damage) if total_damage else 0
            reward = world_boss.roll_world_boss_loot(boss["boss_key"], contribution_scale)
            reward_text = self._resolve_world_boss_reward(winner_id, winner_row["name"], boss["boss_key"], reward)
            lottery_winners.append({"user_id": winner_id, "name": winner_row["name"], "reward_text": reward_text})

        self.db.set_world_boss_status(boss_instance_id, status)
        return {
            "boss": boss, "status": status, "total_damage": total_damage, "contributors": guaranteed_summaries,
            "lottery_winners": lottery_winners,
        }

    def start_world_boss_attack_session(self, user_id: int, name: str) -> dict:
        """/raidboss_attack's entry gate -- opens WorldBossView (see world_boss_view.py) for
        an interactive, round-by-round session instead of instantly resolving a flat flurry
        of swings, so it actually feels like clicking through a raid rather than reading one
        text dump (the boss still never retaliates or risks the player's own HP, by explicit
        design — every cultivation realm can safely join in, same as before, just now with a
        real Attack-button-per-swing feel). Checks + consumes the cooldown ONCE here, up
        front, for the whole up-to-WORLD_BOSS_ATTACKS_PER_COOLDOWN-swing session that
        follows via resolve_world_boss_swing. Returns {"ok": False, "reason": "no_boss"} /
        {"ok": False, "reason": "cooldown", "remaining_seconds"} / {"ok": True, "boss"}."""
        self.maybe_spawn_world_boss()
        boss = self.db.get_active_world_boss()
        if not boss:
            return {"ok": False, "reason": "no_boss"}
        player = self.db.get_or_create_player(user_id, name)
        remaining = self._check_cooldown(player, "last_world_boss_attack_ts", world_boss.WORLD_BOSS_ATTACK_COOLDOWN_SECONDS)
        if remaining > 0:
            return {"ok": False, "reason": "cooldown", "remaining_seconds": remaining}
        self.db.set_timestamp_column(user_id, "last_world_boss_attack_ts", int(time.time()))
        # Spirit Severing Dao Marks -- once per attack session (this cooldown gate covers the
        # whole multi-swing session), not per individual swing, matching hunt/raid/explore's
        # own "once per encounter" grant. No-op below Spirit Severing.
        self.grant_dao_marks(user_id, player)
        return {"ok": True, "boss": boss}

    def resolve_world_boss_swing(self, user_id: int, name: str, boss_instance_id: int) -> dict:
        """One Attack-button click's worth of combat inside an already-open WorldBossView
        session (see start_world_boss_attack_session for the once-per-session cooldown gate)
        -- a single one-directional swing (see world_boss.py's own module docstring for why:
        the doc's own pseudocode never shows the boss retaliating). Re-checks that
        boss_instance_id is still the live boss first, since a long-lived shared target can
        get finished off by someone ELSE mid-session. Returns {"ok": False, "reason":
        "boss_gone"} or {"ok": True, "hit", "dodged", "crit", "damage", "bonus_damage"
        (Flying Sword Gu), "boss_hp_remaining", "boss_max_hp", "defeated", "end_summary"
        (only set if this swing defeated the boss)}."""
        boss = self.db.get_active_world_boss()
        if not boss or boss["boss_instance_id"] != boss_instance_id:
            return {"ok": False, "reason": "boss_gone"}

        player = self.db.get_or_create_player(user_id, name)
        bonuses = self.compute_equipment_bonuses(user_id)
        stats_bonus = bonuses["stats"]
        attacker_stats = {
            "atk_stat": player["atk_stat"] + stats_bonus["atk_stat"],
            "str_stat": player["str_stat"] + stats_bonus["str_stat"],
            "def_stat": player["def_stat"] + stats_bonus["def_stat"],
            "spd_stat": player["spd_stat"] + stats_bonus["spd_stat"],
            "luck_stat": player["luck_stat"] + stats_bonus["luck_stat"],
        }
        boss_stats = {
            "atk_stat": 0, "str_stat": 0, "def_stat": world_boss.WORLD_BOSS_DEF_STAT,
            "spd_stat": world_boss.WORLD_BOSS_SPD_STAT, "luck_stat": 0,
        }
        gu_name = self.db.get_equipped(user_id).get("gu_ability")
        damage_pct_bonus = bonuses.get("physical_damage_pct", 0) + bonuses.get("boss_damage_bonus_pct", 0) + bonuses.get("total_damage_pct", 0)
        if gu_name == "Battle Intent Gu":
            existing = self.db.get_world_boss_damage(boss_instance_id, user_id)
            landed_so_far = existing["attacks"] if existing else 0
            damage_pct_bonus += min(self.WORLD_BOSS_BATTLE_INTENT_MAX_PCT, landed_so_far * self.WORLD_BOSS_BATTLE_INTENT_PCT_PER_ATTACK)

        attack_kwargs = dict(
            crit_chance_bonus=bonuses.get("crit_chance_pct", 0), crit_damage_bonus=bonuses.get("crit_damage_pct", 0),
            damage_pct_bonus=damage_pct_bonus, max_dodge_chance=combat.MONSTER_MAX_DODGE_CHANCE,
            # Nascent Soul Avatar (see avatar.py, Sword Soul) — passive only here, no Soul
            # Projection button for World Boss (deferred, see the approved Phase 2 plan: this
            # view tracks no player Qi/round state at all today, and the boss never
            # retaliates by design, so there's real new infrastructure that would be needed
            # for comparatively little payoff on a boss capped at 5 swings/20min).
            armor_penetration_pct=bonuses.get("armor_penetration_pct", 0),
        )
        result = combat.resolve_attack(attacker_stats, boss_stats, **attack_kwargs)
        swing_damage = result.damage if (result.hit and not result.dodged) else 0

        # Flying Sword Gu: an additional roll on top of this swing, only once it actually
        # connects (a real second hit, not a guaranteed freebie on a miss).
        bonus_damage = 0
        if gu_name == "Flying Sword Gu" and swing_damage > 0:
            bonus_result = combat.resolve_attack(attacker_stats, boss_stats, **attack_kwargs)
            if bonus_result.hit and not bonus_result.dodged:
                bonus_damage = bonus_result.damage

        swing_total = swing_damage + bonus_damage
        defeated, end_summary, hp_remaining = False, None, boss["current_hp"]
        if swing_total > 0:
            hp_remaining = self.db.apply_world_boss_damage(boss_instance_id, swing_total)
            self.db.record_world_boss_attack(boss_instance_id, user_id, name, swing_total)
            if hp_remaining <= 0:
                defeated = True
                end_summary = self._end_world_boss(boss_instance_id, "defeated")

        return {
            "ok": True, "hit": result.hit, "dodged": result.dodged, "crit": result.crit,
            "damage": swing_damage, "bonus_damage": bonus_damage,
            "boss_hp_remaining": 0 if defeated else hp_remaining, "boss_max_hp": boss["max_hp"],
            "defeated": defeated, "end_summary": end_summary,
        }

    # -- PvP Tournament (see game/tournament.py / /tournament) -----------------------------
    # A timed signup window followed by a battle-royale simulation among frozen character
    # "copies" -- mirrors World Boss's own DB-backed, idempotent check-and-act lifecycle
    # (maybe_spawn_world_boss/_end_world_boss) rather than RaidView's in-memory roster, since
    # a tournament's signup window and result need to survive an unplanned bot restart.

    def _tournament_combat_snapshot(self, user_id: int, name: str) -> dict:
        """Frozen ONCE at signup (join_tournament calls this exactly once, ever, per entrant)
        -- unlike opponent_combat_snapshot (/pvp's disposable AI opponent, which deliberately
        skips % bonuses "to keep the AI opponent simple"), a tournament combatant needs their
        real gear/manuals/buffs to matter, so this folds in compute_equipment_bonuses' FULL
        special-bonus pool, not just the 6 flat stats. HP is always full max_hp (+ bonus),
        never the entrant's current possibly-damaged HP -- matches opponent_combat_snapshot's
        own "always full HP" convention. race/physique_tier ride along for
        chargen.race_physique_damage_reduction, the same incoming-hit reduction /pvp already
        applies caller-side."""
        player = self.db.get_or_create_player(user_id, name)
        bonuses = self.compute_equipment_bonuses(user_id)
        sb = bonuses["stats"]
        stats = {
            "atk_stat": player["atk_stat"] + sb["atk_stat"], "str_stat": player["str_stat"] + sb["str_stat"],
            "def_stat": player["def_stat"] + sb["def_stat"], "spd_stat": player["spd_stat"] + sb["spd_stat"],
            "luck_stat": player["luck_stat"] + sb["luck_stat"], "hp": player["max_hp"] + sb["hp"],
        }
        special = {key: bonuses.get(key, 0.0) for key in self.SPECIAL_BONUS_KEYS}
        return {"stats": stats, "special": special, "race": player["race"], "physique_tier": player["physique_tier"]}

    def maybe_open_tournament(self, force: bool = False) -> Optional[dict]:
        """Auto-opens a fresh signup-phase tournament -- mirrors maybe_spawn_world_boss's own
        "auto-recur on a timer" shape (called by the tick loop, and opportunistically by
        TournamentView/open_tournament_signup for freshness). Only ever creates one when none
        is currently active AND TOURNAMENT_COOLDOWN_SECONDS has passed since the previous one's
        ended_ts (or none has ever run) -- TOURNAMENT_COOLDOWN_SECONDS is 0 (see tournament.py),
        so in practice this reopens the instant the previous one resolves, keeping signup open
        continuously while the actual battle royale still only fires once every
        TOURNAMENT_SIGNUP_SECONDS (4 hours). force=True (used by open_tournament_signup, which
        already did its own cooldown check for the player-facing error message) skips the
        cooldown re-check. Returns the newly created tournament row, or None if nothing changed
        this call."""
        if self.db.get_active_tournament() is not None:
            return None
        now = int(time.time())
        latest = self.db.get_latest_tournament()
        if not force and latest and latest["ended_ts"] and now - latest["ended_ts"] < tournament.TOURNAMENT_COOLDOWN_SECONDS:
            return None
        tournament_id = self.db.create_tournament(now, now + tournament.TOURNAMENT_SIGNUP_SECONDS)
        return self.db.get_tournament(tournament_id)

    def open_tournament_signup(self, user_id: int, name: str) -> dict:
        """/tournament's "Start Tournament" button. Idempotent against two simultaneous
        clicks -- if a tournament is already active by the time this runs, just joins the
        caller into THAT one instead of creating a duplicate (only one row with status IN
        ('signup','running') is ever allowed, enforced here in Python, mirroring
        maybe_spawn_world_boss's own convention). Since maybe_open_tournament now also keeps
        signup open continuously on its own (TOURNAMENT_COOLDOWN_SECONDS is 0 -- see
        tournament.py), this is mostly a manual fallback so a player can open the very first
        one, or recover from an unexpected gap, without waiting for the next 5-minute tick --
        still gated by the same TOURNAMENT_COOLDOWN_SECONDS check as maybe_open_tournament,
        just with a player-facing message on top."""
        active = self.db.get_active_tournament()
        if active is None:
            now = int(time.time())
            latest = self.db.get_latest_tournament()
            if latest and latest["ended_ts"] and now - latest["ended_ts"] < tournament.TOURNAMENT_COOLDOWN_SECONDS:
                remaining = tournament.TOURNAMENT_COOLDOWN_SECONDS - (now - latest["ended_ts"])
                minutes = max(1, remaining // 60)
                return {
                    "tournament": None, "join_ok": False,
                    "join_message": f"The next tournament isn't ready yet — try again in about {minutes} minute(s).",
                }
            active = self.maybe_open_tournament(force=True)
        ok, message = self.join_tournament(user_id, name)
        return {"tournament": self.db.get_tournament(active["tournament_id"]), "join_ok": ok, "join_message": message}

    def join_tournament(self, user_id: int, name: str) -> tuple:
        self.resolve_tournament_if_ready()  # settle anything overdue first -- same freshness pattern get_world_boss_status uses
        active = self.db.get_active_tournament()
        if active is None or active["status"] != "signup":
            return False, "There's no tournament signing up right now — try Start Tournament."
        if self.db.get_tournament_participant(active["tournament_id"], user_id):
            return False, "You're already signed up for this tournament."
        if len(self.db.get_tournament_participants(active["tournament_id"])) >= tournament.TOURNAMENT_MAX_PARTICIPANTS:
            return False, f"This tournament is full ({tournament.TOURNAMENT_MAX_PARTICIPANTS} max)."
        player = self.db.get_or_create_player(user_id, name)
        if not player["character_confirmed"]:
            return False, "You need to `/join` and confirm a character first."
        snapshot = self._tournament_combat_snapshot(user_id, name)
        self.db.add_tournament_participant(active["tournament_id"], user_id, name, snapshot)
        count = len(self.db.get_tournament_participants(active["tournament_id"]))
        return True, f"You've entered the tournament! {count} cultivator(s) signed up so far."

    def leave_tournament(self, user_id: int) -> tuple:
        active = self.db.get_active_tournament()
        if active is None or active["status"] != "signup":
            return False, "You can only leave during the signup phase."
        if not self.db.get_tournament_participant(active["tournament_id"], user_id):
            return False, "You're not signed up for this tournament."
        self.db.remove_tournament_participant(active["tournament_id"], user_id)
        return True, "You've withdrawn from the tournament."

    def resolve_tournament_if_ready(self) -> Optional[dict]:
        """Idempotent check-and-act, called by the tick loop AND opportunistically by
        join_tournament/get_tournament_status (mirrors maybe_spawn_world_boss's "also called
        from player-facing commands" pattern) -- so whichever happens first, a player running
        /tournament or /cd or the 5-minute tick, is the one that actually flips a
        signup/running tournament to completed/cancelled. Returns a summary dict to
        announce/DM, or None if nothing changed. IMPORTANT: the direct return value is only
        ever consumed by the tick loop's own immediate call, and every non-tick caller
        discards it -- announcing/DMing must NOT be wired to this return value alone (see
        get_pending_tournament_announcements, which is what actually guarantees an announcement
        regardless of which caller was the one that resolved it)."""
        now = int(time.time())
        active = self.db.get_active_tournament()
        if active is None:
            return None
        if active["status"] == "signup" and active["signup_ends_ts"] <= now:
            participants = self.db.get_tournament_participants(active["tournament_id"])
            if len(participants) < tournament.TOURNAMENT_MIN_PARTICIPANTS:
                self.db.cancel_tournament(active["tournament_id"])
                return {"outcome": "cancelled", "tournament_id": active["tournament_id"], "participant_count": len(participants)}
            self.db.start_tournament(active["tournament_id"])
            return self._run_and_complete_tournament(active["tournament_id"], participants)
        if active["status"] == "running" and active["started_ts"] and now - active["started_ts"] > tournament.TOURNAMENT_RUNNING_STALE_SECONDS:
            # Rare crash-recovery path: a process kill mid-resolution could otherwise leave a
            # tournament stuck 'running' forever. Safe to re-run -- the frozen snapshots
            # already persisted at signup make the whole simulation fully re-derivable from DB
            # state alone, nothing in-memory to have lost.
            return self._run_and_complete_tournament(active["tournament_id"], self.db.get_tournament_participants(active["tournament_id"]))
        return None

    def get_pending_tournament_announcements(self) -> list:
        """The single choke point GameCog.tournament_tick uses to decide what to post/DM --
        NOT resolve_tournament_if_ready's own return value. Fixes a real bug: resolve_tournament_
        if_ready is also called opportunistically by join_tournament and get_tournament_status
        (i.e. by an ordinary player running /tournament, /cd, or hitting Join), so a tournament
        could -- and in practice regularly did -- get resolved by one of THOSE calls in the gap
        between two ticks. Those callers discard the return value, so the tournament finished
        with rewards silently granted but zero channel post and zero placement DMs. Settles
        anything overdue first (same as before), then returns every completed/cancelled
        tournament that hasn't been marked announced yet, in the same shape
        resolve_tournament_if_ready's own return value used -- caller must call
        mark_tournament_announced on each one once it's actually posted, so a tournament is
        never announced twice even if this is called again before that happens."""
        self.resolve_tournament_if_ready()
        pending = []
        for row in self.db.get_unannounced_tournament_results():
            if row["status"] == "completed":
                pending.append({
                    "outcome": "completed", "tournament_id": row["tournament_id"],
                    "placements": row["result_log"]["placements"],
                })
            else:
                participant_count = len(self.db.get_tournament_participants(row["tournament_id"]))
                pending.append({
                    "outcome": "cancelled", "tournament_id": row["tournament_id"],
                    "participant_count": participant_count,
                })
        return pending

    def mark_tournament_announced(self, tournament_id: int):
        self.db.mark_tournament_announced(tournament_id)

    def get_tournament_status(self) -> tuple:
        """(phase, row) -- phase is 'none'/'signup'/'running'/'completed_recent'. Settles
        anything overdue first, then opportunistically opens a fresh signup (cooldown is 0, so
        this basically always succeeds immediately once none is active) in case the tick loop
        hasn't caught up yet (mirrors get_world_boss_status's own "settle, then maybe spawn,
        before showing" pattern), so every caller (TournamentView, /cd) always sees the exact
        same, always-fresh state through one shared code path -- in practice that means
        'signup' almost all the time, since there's no real cooldown gap for 'none' or
        'completed_recent' to persist through anymore."""
        self.resolve_tournament_if_ready()
        self.maybe_open_tournament()
        active = self.db.get_active_tournament()
        if active is not None:
            return active["status"], active
        latest = self.db.get_latest_tournament()
        if (
            latest is not None and latest["status"] == "completed"
            and int(time.time()) - (latest["ended_ts"] or 0) < tournament.TOURNAMENT_COMPLETED_DISPLAY_SECONDS
        ):
            return "completed_recent", latest
        return "none", latest

    def _run_and_complete_tournament(self, tournament_id: int, participants: list) -> dict:
        # Essence of the Undying Vow (see game/dao_essences.py) -- checked FRESH here rather
        # than baked into the frozen-at-signup snapshot (unlike every other stat/special bonus
        # in that snapshot), since it's a permanent essence pick, not a build-time gear/buff
        # snapshot -- correctly reflects a pick made after signup but before the battle
        # actually fires, and stays consistent across the crash-recovery re-run path too (both
        # callers of this method route through here).
        for p in participants:
            p["has_undying_vow"] = dao_essences.UNDYING_VOW_NAME in self.db.get_dao_essences_picked(p["user_id"])
        result = tournament.run_battle_royale(participants)
        placements = []
        for entry in result["placements"]:
            summary = self._grant_tournament_placement_reward(entry["user_id"], entry["name"], entry["rank"])
            self.db.set_tournament_participant_result(tournament_id, entry["user_id"], entry["rank"])
            placements.append({**entry, "reward_summary": summary})

        # Bonus Essence Restoration Pill lottery -- independent of placement (everyone who
        # signed up and fought has an equal shot, not weighted by rank), per explicit request.
        # Folded directly into each winner's own reward_summary rather than a separate field,
        # so every existing renderer (cog.py's channel/DM text, tournament_view.py's embed)
        # picks it up automatically with zero UI changes needed.
        for user_id, tier in tournament.roll_bonus_pill_winners([p["user_id"] for p in placements]):
            pill_name = items.alchemy_pill_name("Essence Restoration", tier)
            self.db.add_item(user_id, pill_name, 1)
            winner_entry = next(p for p in placements if p["user_id"] == user_id)
            winner_entry["reward_summary"] += f" + 🎁 Bonus: 1x {pill_name}"

        # Bonus Epic Gu lottery -- same flat, placement-independent shape as the pill lottery
        # above, per explicit request.
        for user_id, gu_family in tournament.roll_bonus_epic_gu_winners([p["user_id"] for p in placements]):
            gu_name = equipment.gu_item_name(gu_family, "Epic")
            self.db.add_item(user_id, gu_name, 1)
            winner_entry = next(p for p in placements if p["user_id"] == user_id)
            winner_entry["reward_summary"] += f" + 🎁 Bonus: 1x {gu_name}"

        # Bonus Nascent Soul avatar gear -- one chance-gated roll for the whole tournament (not
        # guaranteed, unlike the two lotteries above), per explicit request. Only eligible among
        # participants who've actually unlocked their avatar, so the roll is never wasted on
        # someone who couldn't equip it -- if nobody here has, the roll silently doesn't fire.
        if tournament.roll_bonus_avatar_gear_chance():
            eligible = [p for p in placements if self.is_avatar_unlocked(p["user_id"], p["name"])]
            if eligible:
                winner_entry = random.choice(eligible)
                grant = self.roll_and_grant_avatar_gear(
                    winner_entry["user_id"], winner_entry["name"],
                    "tournament_bonus", tournament.TOURNAMENT_BONUS_AVATAR_GEAR_SOURCE_TIER,
                )
                winner_entry["reward_summary"] += f" + 🎁 Bonus: a {avatar_gear.tier_name(grant['tier'])} {grant['slot_type']} avatar gear"

        result_log = {
            "events": result["events"], "placements": placements,
            "rounds_used": result["rounds_used"], "capped": result["capped"],
        }
        self.db.complete_tournament(tournament_id, result_log)
        return {"outcome": "completed", "tournament_id": tournament_id, "placements": placements}

    def _grant_tournament_placement_reward(self, user_id: int, name: str, rank: int) -> str:
        # Spirit Severing Dao Marks -- every placement gets the same flat 1-3 grant hunt/raid/
        # explore give, regardless of rank; silently a no-op below Spirit Severing.
        self.grant_dao_marks(user_id)
        entry = tournament.TOURNAMENT_PLACEMENT_REWARDS.get(rank)
        if entry is None:
            stones = tournament.participation_stones(rank)
            self.db.add_spirit_stones(user_id, stones)
            crystal_qty = tournament.TOURNAMENT_PARTICIPATION_ESSENCE_CRYSTAL_QTY
            self.db.add_item(user_id, "Primeval Essence Crystal", crystal_qty)
            return f"{format_number(stones)} 🪙 + {crystal_qty}x Primeval Essence Crystal (rank {rank})"
        parts = []
        self.db.add_spirit_stones(user_id, entry["stones"])
        parts.append(f"{format_number(entry['stones'])} 🪙")
        self.db.add_item(user_id, "Primeval Essence Crystal", entry["essence_crystal_qty"])
        parts.append(f"{entry['essence_crystal_qty']}x Primeval Essence Crystal")
        gu_family = random.choice([f for f, d in equipment.GU_FAMILIES.items() if entry["gu_quality"] in d["qualities"]])
        gu_name = equipment.gu_item_name(gu_family, entry["gu_quality"])
        self.db.add_item(user_id, gu_name, 1)
        parts.append(gu_name)
        pill_name = items.alchemy_pill_name("Essence Restoration", entry["essence_pill_tier"])
        self.db.add_item(user_id, pill_name, entry["essence_pill_qty"])
        parts.append(f"{entry['essence_pill_qty']}x {pill_name}")
        if self.is_avatar_unlocked(user_id, name) and random.random() < entry["avatar_gear_chance"]:
            grant = self.roll_and_grant_avatar_gear(user_id, name, "tournament", entry["avatar_gear_source_tier"])
            parts.append(f"a {avatar_gear.tier_name(grant['tier'])} {grant['slot_type']} avatar gear")
        if random.random() < entry["crafted_gear_chance"]:
            tier = random.randint(*entry["crafted_gear_tier_range"])
            base_type = random.choice(list(equipment.BLACKSMITH_GEAR_SLOT_TYPE.keys()))
            stat_bonuses = blacksmith.roll_gear_stats(tier, random.Random())
            parts.append(self.grant_reward(user_id, name, {
                "kind": "crafted_gear", "base_type": base_type, "tier": tier, "stat_bonuses": stat_bonuses,
            }))
        return " + ".join(parts)
