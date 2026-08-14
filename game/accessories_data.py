"""
Static content for the accessories/artifacts system (see
insanity_accessories_and_artifacts_system.md) — rank/rarity power budgets, the mechanic
cost guide, drawback table, name-generation word banks, loot source odds, set bonuses, and
the full 73-item hand-authored catalog (36 accessories + 37 artifacts), mirroring how
manual_data.py holds the manual-page catalog and GU_FAMILIES holds tiered Gu.

Adaptation notes (this bot doesn't have every system the design doc assumes — same
"fold the unbuildable bits into what already exists" approach manual_data.py/discovery_gen.py
already took for the manual system's exotic materials):
  - No general combat status-effect system exists (no stun/silence/fear/confusion) — items
    referencing "negate a control effect" or "reflect fear/charm/confusion" are implemented
    as a plain damage-reduction shield instead (effect_key "encounter_shield").
  - Defeat only costs Qi in this bot (see hunt.py's qi_lost_on_death) — there's no item loss
    on defeat to protect against, so "death ward" / "preserve item on defeat" items both
    negate that Qi-loss penalty once per day instead (effect_key "defeat_ward_daily").
  - No inventory size cap exists, so "+N inventory slots" items keep their flavor text but
    carry a small compensating stat_bonus instead of a slot count that would do nothing.
  - No NPC item-purchase marketplace exists (just /shop's spirit-stone reroll costs) — "NPC
    prices" effects instead shave a little off /premium's reroll/race-change costs.
  - No travel-time mechanic exists — "faster travel" effects instead shave a little off
    /search's charge recharge time (the closest analog to "getting around faster").
  - No world boss, tribulation, auction, or formal party system exist — "party"-flavored
    effects key off /raid's multi-participant roster (the only multiplayer combat that does
    exist); world boss/tribulation/auction-sourced items are reachable through /search
    discoveries and dismantling instead (see the LOOT_SOURCE_TABLE adaptation below).
  - "Rule/domain" and other Rank 6-7 signature effects for 4 of the Unique items get real,
    individually hand-implemented behavior (see manager.py's GameManager._activate_unique_
    signature) rather than a generic mechanic, matching the doc's own "hand-authored" framing
    for Unique-rarity items. The Gourd of Reversed Rivers was the 5th, originally described
    as reverting HP/essence/combat state once every 7 days -- simplified 2026-08-10 (user's
    explicit request) to a full daily primeval essence restore instead (effect_key
    "essence_restore_charges", same mechanic the Springwater Essence Gourd/Dew-Gathering Jade
    Ring already use, just at 100% instead of a smaller %), since the original revert idea
    had no snapshot/restore hook anywhere in hunt.py/raid.py/pvp_view.py to actually run on.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# -- Rank power budget (section 3) ------------------------------------------------------------
RANK_POWER_BUDGET = {1: 2, 2: 4, 3: 7, 4: 11, 5: 16, 6: 24, 7: 34}

# -- Rarity budget multipliers + roll odds (sections 3, 5) -------------------------------------
RARITY_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic", "Unique"]
RARITY_BUDGET_MULTIPLIER = {
    "Common": 1.00, "Uncommon": 1.20, "Rare": 1.50, "Epic": 1.90,
    "Legendary": 2.40, "Mythic": 3.00, "Unique": None,  # Unique: hand-authored, no formula
}
ACCESSORY_RARITY_WEIGHTS = {
    "Common": 46.0, "Uncommon": 28.0, "Rare": 15.0, "Epic": 7.0,
    "Legendary": 3.0, "Mythic": 0.8, "Unique": 0.2,
}
ARTIFACT_RARITY_WEIGHTS = {
    "Common": 30.0, "Uncommon": 30.0, "Rare": 20.0, "Epic": 11.0,
    "Legendary": 6.0, "Mythic": 2.5, "Unique": 0.5,
}

# -- Attunement (section 2) ---------------------------------------------------------------------
ATTUNEMENT_REQUIRED_RARITIES = {"Legendary", "Mythic", "Unique"}
MAX_MORTAL_ATTUNEMENTS = 2  # before Rank 6 (immortal) — one immortal attunement instead


def attunement_cost(affix: "Affix") -> int:
    """Rank 6-7 ("immortal") attunement spends the whole budget at once; everything else
    costs 1. Shared by GameManager.attune_accessory_artifact/_release_attunement AND
    GameDatabase.execute_trade/execute_gamble's own transfer-time refund logic (giving up an
    attuned item -- salvaging, trading, or losing a gamble -- always frees the capacity it
    used, per explicit bug report/fix request)."""
    return 2 if affix.rank >= 6 else 1

# -- Cultivation/search-luck caps (section 4) ---------------------------------------------------
EQUIPMENT_CULTIVATION_CAP_PCT = 35.0
EQUIPMENT_SEARCH_LUCK_CAP_PCT = 50.0

# -- Mechanic cost guide (section 3's "Mechanic Cost Guide" table) -----------------------------
# {effect_key: (budget_cost, guardrail_text)} — used by item_gen.py's procedural generator to
# "shop" for effects within a rolled item's power budget.
MECHANIC_COST_GUIDE = {
    "cultivation_boost": (1, "Cap ordinary passive cultivation bonuses from equipment at +35% (see EQUIPMENT_CULTIVATION_CAP_PCT)."),
    "stat": (1, "Additive within the same stat family."),
    "clue_chance": (1, "Cap total equipment detection/clue bonus at +50% (see EQUIPMENT_SEARCH_LUCH_CAP_PCT)."),
    "encounter_shield": (2, "Usually 5-10% max HP equivalent, first few enemy actions only."),
    "post_action_buff": (4, "Once per encounter."),
    "extra_loot_roll_daily": (4, "Independent roll; excludes jackpots."),
    "search_reroll_daily": (5, "Daily; second result is final."),
    "defeat_ward_daily": (6, "Daily and random or preselected with a fee."),
    "loot_duplicate_daily": (10, "Daily; strict exclusions and temporary binding."),
    "breakthrough_boost_daily": (12, "Rank 5+; daily; applies a meaningful penalty."),
    "refresh_artifact_weekly": (14, "Cannot refresh death or loot-duplication mechanics."),
    "unique_signature": (16, "Rank 6+; immortal essence upkeep and exclusivity."),
}

# -- Drawback table (section 10 "Recommended Drawbacks") ----------------------------------------
@dataclass
class Drawback:
    drawback_id: str
    text: str
    budget_refund_pct: float


DRAWBACKS: Dict[str, Drawback] = {
    "essence_hungry": Drawback("essence_hungry", "Active effects cost 20% more essence.", 0.20),
    "path_conflict": Drawback("path_conflict", "Opposed-path skills lose 8% effectiveness while equipped.", 0.25),
    "cracked_after_use": Drawback("cracked_after_use", "Signature effect disables the item until daily reset.", 0.30),
    "blood_price": Drawback("blood_price", "Signature activation costs current HP.", 0.30),
    "karmic_exposure": Drawback("karmic_exposure", "Raises ambush/attention after a major reward.", 0.35),
    "bound_on_activation": Drawback("bound_on_activation", "Trading is disabled after the signature effect is first used.", 0.20),
    "unstable_refinement": Drawback("unstable_refinement", "Small chance of temporary backlash when activated.", 0.40),
}
DRAWBACK_ROLL_CHANCE = 0.35  # at Epic+ rarity, per section 10

# -- Name generation word banks (section 10) -----------------------------------------------------
NAME_MATERIALS = ["Jade", "Vermilion", "Bone", "Black Iron", "Moon-Silver", "Cloud Silk", "Beast Fang", "Star Sand"]
NAME_CONCEPTS = ["Fortune", "Reversal", "Silence", "Blood Debt", "Wandering", "Calamity", "Dream", "Inheritance", "Echo", "Last Breath"]
NAME_FORMS_ACCESSORY = {"Ring": ["Ring"], "Earring": ["Earring", "Ear Cuff"], "Necklace": ["Pendant", "Necklace", "Locket"], "Bracelet": ["Wrist Cord", "Bracer", "Belt", "Brooch"]}
NAME_FORMS_ARTIFACT = ["Gourd", "Flying Sword", "Mirror", "Lantern", "Bell", "Fan", "Umbrella", "Boat", "Cauldron", "Pagoda", "Seal", "Banner"]

# -- Loot source tables (section 6) — adapted onto this bot's real systems ----------------------
# Percent chance a kill/chest/discovery step rolls an accessory or artifact category at all
# (BEFORE the rarity table above picks its rarity). "ordinary"/"elite" map onto /hunt and
# /raid kills (no elite-monster tier exists yet, so /raid's boss stands in for "elite");
# "world_boss"/"tribulation"/"auction" have no equivalent system in this bot at all, so their
# odds are folded into /search's discovery final chests instead (inheritance_final ~=
# inheritance core, secret_realm_boss ~= secret realm final vault, dream_completion ~= dream
# realm completion) — nothing in the design doc's loot table is simply dropped.
LOOT_SOURCE_TABLE = {
    "hunt_kill": {"accessory": 0.02, "artifact": 0.0025},
    # Briefly bumped 5x for a "raid takes a whole day, should feel rewarding" experiment,
    # then scaled back to its original rate once that generosity moved over to World Boss
    # instead (see world_boss's own entry below) -- raid_boss is back to sitting below it.
    "raid_boss": {"accessory": 0.08, "artifact": 0.015},
    # World Boss (see world_boss.py / GameManager.attack_world_boss) -- now the deliberately
    # bigger, more generous communal-event target (the "big increase" that raid_boss
    # temporarily had moved here instead), well above every other source except the
    # dedicated secret-realm/inheritance final-chest rewards.
    "world_boss": {"accessory": 0.60, "artifact": 0.15},
    "inheritance_room": {"accessory": 0.12, "artifact": 0.06},
    "inheritance_final": {"accessory": 0.30, "artifact": 0.25},
    "secret_realm_room": {"accessory": 0.10, "artifact": 0.05},
    "secret_realm_final": {"accessory": 0.32, "artifact": 0.28},
    "dream_realm_stage": {"accessory": 0.09, "artifact": 0.0},
    "dream_realm_final": {"accessory": 0.14, "artifact": 0.09},
    # Nascent Soul Avatar's /split_body mission (see game/split_body.py) -- passive/no-risk
    # but takes 3 real-world hours, so it sits above hunt_kill and below raid_boss.
    "split_body": {"accessory": 0.05, "artifact": 0.01},
    # /search_forgotten_blessed_land's treasure-hunt board (see game/treasure_hunt.py) -- used
    # both by the board's "rare-ish" tile bucket and its guaranteed treasure tile's bonus roll,
    # always called with source_rank=7 (meant to feel special either way). Sits between
    # raid_boss and world_boss: rarer to encounter than a raid (one guaranteed accessory-ish
    # shot per cooldown, not a whole boss fight), but not the big communal event World Boss is.
    "treasure_hunt": {"accessory": 0.55, "artifact": 0.20},
}
# Path weighting (section 6): once a category is chosen, items sharing a source's theme tags
# get 3x weight, neutral items 1x, opposed-path items 0.35x — see item_gen.select_named_item.
PATH_MATCH_WEIGHT = 3.0
PATH_NEUTRAL_WEIGHT = 1.0
PATH_OPPOSED_WEIGHT = 0.35


@dataclass
class Affix:
    item_id: str
    name: str
    category: str  # "Accessory" | "Artifact"
    slot_type: str  # "Ring"/"Earring"/"Necklace"/"Bracelet" (accessory) or "Artifact"
    family: str  # doc's own Slot/Type column, for flavor + procedural naming (e.g. "Gourd")
    rank: int  # 1-7
    rarity: str
    paths: List[str]
    description: str
    limit_text: str
    effect_key: str
    effect_params: dict = field(default_factory=dict)
    stat_bonuses: Dict[str, float] = field(default_factory=dict)
    pair_slot_keys: Optional[tuple] = None  # ("ring_1","ring_2") etc — for "wearing both" bonuses


ITEMS: Dict[str, Affix] = {}


def _reg(item_id, name, category, slot_type, family, rank, rarity, paths, desc, limit,
         effect_key, effect_params=None, stat_bonuses=None, pair_slot_keys=None):
    ITEMS[item_id] = Affix(
        item_id=item_id, name=name, category=category, slot_type=slot_type, family=family,
        rank=rank, rarity=rarity, paths=[p.strip().lower() for p in paths.split(",")] if paths else [],
        description=desc, limit_text=limit, effect_key=effect_key,
        effect_params=effect_params or {}, stat_bonuses=stat_bonuses or {}, pair_slot_keys=pair_slot_keys,
    )


# ================================================================================================
# 7. ACCESSORY LOOT POOL
# ================================================================================================

# -- Rings ---------------------------------------------------------------------------------------
_reg("acc_dew_gathering_jade_ring", "Dew-Gathering Jade Ring", "Accessory", "Ring", "Ring", 1, "Common",
     "Water, Refinement", "The first cultivation action each day restores 6% primeval essence.",
     "Once per day; cannot overfill essence.", "essence_restore_charges", {"charges": 1, "pct": 0.06})
_reg("acc_stone_marrow_ring", "Stone-Marrow Ring", "Accessory", "Ring", "Ring", 1, "Uncommon",
     "Earth", "Gain +4% maximum HP and take 3% less damage while above 70% HP.",
     "Damage reduction does not stack with another Stone-Marrow effect.",
     "stat", stat_bonuses={"hp": 16, "beast_damage_reduction_pct": 0.03})
_reg("acc_quiet_cicada_ring", "Quiet Cicada Ring", "Accessory", "Ring", "Ring", 2, "Rare",
     "Sound, Wisdom", "Reduces the cooldown of non-combat search commands by 5% and grants +5% clue quality.",
     "Only the strongest search-cooldown accessory applies.", "clue_chance",
     stat_bonuses={"search_recharge_reduction_pct": 0.05, "clue_chance_bonus_pct": 0.05})
_reg("acc_ember_heart_signet", "Ember-Heart Signet", "Accessory", "Ring", "Ring", 2, "Rare",
     "Fire", "After spending at least 30% of maximum essence in one encounter, gain +12% damage for the next two attacks.",
     "Once per encounter.", "post_action_buff", {"trigger": "encounter_start", "atk_pct": 0.12, "duration_seconds": 60})
_reg("acc_twin_fortune_rings", "Twin Fortune Rings", "Accessory", "Ring", "Ring Set", 3, "Epic",
     "Luck", "Each ring gives +4% loot luck. Wearing both grants one extra independent common-or-uncommon loot roll after a boss.",
     "The bonus roll cannot produce quest, unique, guaranteed, or jackpot rewards.",
     "extra_loot_roll_daily", {"pair_bonus": True}, stat_bonuses={"loot_chance_bonus_pct": 0.04},
     pair_slot_keys=("ring_1", "ring_2"))
_reg("acc_blood_debt_ring", "Blood-Debt Ring", "Accessory", "Ring", "Ring", 3, "Epic",
     "Blood, Demonic", "Sacrifice 12% current HP to increase the next cultivation gain by 25%.",
     "Once per day; cannot be used below 30% HP.", "breakthrough_boost_daily", {"hp_cost_pct": 0.12, "cultivation_pct": 0.25})
_reg("acc_moon_shadow_storage_ring", "Moon-Shadow Storage Ring", "Accessory", "Ring", "Ring", 4, "Legendary",
     "Space, Shadow", "Adds 12 inventory slots. Once per day, protect one randomly selected non-bound item from being lost on defeat.",
     "Does not protect currency, quest items, or items consumed before defeat.",
     "defeat_ward_daily", {}, stat_bonuses={"loot_chance_bonus_pct": 0.03})
_reg("acc_reversal_of_misfortune_ring", "Reversal of Misfortune Ring", "Accessory", "Ring", "Ring", 4, "Legendary",
     "Luck, Wisdom", "When a loot roll produces only the lowest available rarity, reroll the highest-value slot once.",
     "Once per day; must accept the second result; no jackpot rerolls.", "search_reroll_daily", {})
_reg("acc_life_retaining_vermilion_ring", "Life-Retaining Vermilion Ring", "Accessory", "Ring", "Ring", 5, "Mythic",
     "Human, Blood", "When lethal damage is taken, survive at 1 HP, cleanse one disabling effect, and end the enemy's current combo.",
     "Once per daily reset; lose 20% current essence and the ring becomes Cracked until reset.",
     "defeat_ward_daily", {"essence_cost_pct": 0.20})
_reg("acc_empty_aperture_ring", "Empty Aperture Ring", "Accessory", "Ring", "Ring", 5, "Legendary",
     "Space, Rule", "Stores up to 20% of essence spent while at maximum cultivation efficiency. Release it to reduce the cost of one breakthrough attempt.",
     "Storage empties after seven days; cannot reduce a breakthrough below 70% of its normal cost.",
     "breakthrough_boost_daily", {"cost_reduction_pct": 0.20})
_reg("acc_dao_echo_ring", "Dao-Echo Ring", "Accessory", "Ring", "Ring", 6, "Mythic",
     "Rule, Wisdom", "Copies 20% of the numerical benefit of the other equipped ring if both share at least one path tag.",
     "Cannot copy cooldowns, death wards, extra-drop rolls, or Unique effects.",
     "stat", stat_bonuses={"loot_chance_bonus_pct": 0.04, "cultivation_speed_pct": 0.02})
_reg("acc_ring_of_trials", "Ring of the Ten-Thousand-Trial Survivor", "Accessory", "Ring", "Ring", 7, "Unique",
     "Human, Heaven", "After failing a breakthrough, permanently gain a small Failure Insight stack. At 10 stacks, the next breakthrough cannot critically fail and consumes all stacks.",
     "Maximum one Failure Insight per day; does not guarantee success.",
     "unique_signature", {"handler": "ring_of_trials"})

# -- Earrings --------------------------------------------------------------------------------
_reg("acc_wind_listening_earring", "Wind-Listening Earring", "Accessory", "Earring", "Earring", 1, "Common",
     "Wind, Information", "Gain +6% chance to detect ambushes, traps, or hidden rooms during searches.",
     "Detection reveals danger but does not automatically avoid it.", "clue_chance", {}, stat_bonuses={"clue_chance_bonus_pct": 0.02})
_reg("acc_clear_bell_earring", "Clear-Bell Earring", "Accessory", "Earring", "Earring", 1, "Uncommon",
     "Sound, Soul", "Mental and dream-realm penalties expire 10% faster.",
     "Does not shorten permanent injuries or account-wide cooldowns.", "stat", stat_bonuses={"essence_regen_pct": 0.02})
_reg("acc_swallow_tail_earrings", "Swallow-Tail Earrings", "Accessory", "Earring", "Earring Set", 2, "Rare",
     "Wind, Movement", "Each gives +3% evasion. Wearing both lets the player retreat from one ordinary encounter without a loot penalty.",
     "Once per day; cannot escape bosses, tribulations, or PvP challenges.",
     "stat", stat_bonuses={"dodge_chance_pct": 0.03}, pair_slot_keys=("earring_1", "earring_2"))
_reg("acc_truth_hearing_pearl", "Truth-Hearing Pearl", "Accessory", "Earring", "Earring", 3, "Epic",
     "Information, Wisdom", "Shows one hidden property, drawback, or activation condition on an unidentified item.",
     "Three uses per day; does not reveal server-secret puzzle answers.", "search_reroll_daily", {"charges": 3})
_reg("acc_dream_sifting_earring", "Dream-Sifting Earring", "Accessory", "Earring", "Earring", 3, "Rare",
     "Dream, Soul", "When completing a dream-realm stage, gain a 15% chance to keep one temporary insight as a permanent minor insight.",
     "At most one permanent insight per dream realm.", "stat", stat_bonuses={"loot_chance_bonus_pct": 0.03})
_reg("acc_thunderclap_ear_cuff", "Thunderclap Ear Cuff", "Accessory", "Earring", "Earring", 4, "Legendary",
     "Lightning, Sound", "The first time the wearer is stunned or silenced in an encounter, negate it and deal a small lightning counterattack.",
     "Once per encounter.", "encounter_shield", {"reduction_pct": 0.15, "hits": 1})
_reg("acc_whisper_of_ancient_intent", "Whisper of Ancient Intent", "Accessory", "Earring", "Earring", 5, "Mythic",
     "Wisdom, Soul", "Once per day, ask an inheritance spirit for a weighted hint showing which of three choices is least dangerous.",
     "The hint is probabilistic and may be distorted in demonic inheritances.", "search_reroll_daily", {})
_reg("acc_heaven_defying_echo_earrings", "Heaven-Defying Echo Earrings", "Accessory", "Earring", "Earring Set", 6, "Unique",
     "Sound, Heaven", "After a daily-limited artifact triggers, gain an Echo token. Spend three Echo tokens to refresh a non-death, non-drop-doubling daily artifact.",
     "Maximum one Echo token per day; token cap three.", "unique_signature", {"handler": "echo_earrings"},
     pair_slot_keys=("earring_1", "earring_2"))

# -- Necklaces -------------------------------------------------------------------------------
_reg("acc_warm_jade_meridian_pendant", "Warm-Jade Meridian Pendant", "Accessory", "Necklace", "Necklace", 1, "Common",
     "Human, Healing", "Natural HP recovery is increased by 8% and cultivation injuries cost 5% less to treat.",
     "Does not reduce instant revival costs.", "stat", stat_bonuses={"essence_regen_pct": 0.02, "hp": 8})
_reg("acc_beast_fang_necklace", "Beast-Fang Necklace", "Accessory", "Necklace", "Necklace", 2, "Uncommon",
     "Transformation, Strength", "Gain +8% damage against beasts and +5% beast-material drop quantity.",
     "Material quantity bonus rounds down and cannot create rare cores.", "stat", stat_bonuses={"str_stat": 3, "stone_reward_bonus_pct": 0.03})
_reg("acc_three_breath_protection_pendant", "Three-Breath Protection Pendant", "Accessory", "Necklace", "Necklace", 2, "Rare",
     "Qi, Defense", "At the start of battle, gain a shield equal to 8% maximum HP for the first three enemy actions.",
     "Shield expires after the third enemy action.", "encounter_shield", {"reduction_pct": 0.08, "hits": 3})
_reg("acc_cloud_step_talisman_necklace", "Cloud-Step Talisman Necklace", "Accessory", "Necklace", "Necklace", 3, "Epic",
     "Cloud, Movement", "Reduces travel time by 12%. The first movement check in a secret realm is automatically treated as one grade better.",
     "Cannot turn a critical failure into a success.", "clue_chance",
     stat_bonuses={"search_recharge_reduction_pct": 0.05})
_reg("acc_ancestors_sealed_locket", "Ancestor's Sealed Locket", "Accessory", "Necklace", "Necklace", 4, "Legendary",
     "Soul, Enslavement", "Stores the imprint of one defeated non-boss creature. Summon the imprint once per day for a temporary combat assist.",
     "Imprint power is capped at 20% of the player's combat rating.", "post_action_buff", {"trigger": "encounter_start", "str_pct": 0.10, "duration_seconds": 90})
_reg("acc_golden_thread_karma_necklace", "Golden Thread Karma Necklace", "Accessory", "Necklace", "Necklace", 4, "Legendary",
     "Luck, Human", "Helping another player grants a Karma thread. At five threads, consume them to add a guaranteed Rare-or-better roll to a cooperative boss chest.",
     "One thread per player per day; no self-trading loops.", "stat", stat_bonuses={"loot_chance_bonus_pct": 0.06})
_reg("acc_nine_deaths_black_pearl", "Nine-Deaths Black Pearl", "Accessory", "Necklace", "Necklace", 5, "Mythic",
     "Soul, Dark", "On defeat, preserve all cultivation progress and equipped-item durability.",
     "Once every seven days; does not prevent the defeat or preserve unbound loot.", "defeat_ward_daily", {"weekly": True})
_reg("acc_aperture_stabilizing_chain", "Aperture-Stabilizing Chain", "Accessory", "Necklace", "Necklace", 6, "Mythic",
     "Rule, Qi", "Reduces deviation chance during high-risk cultivation by 20% and converts the first severe deviation each week into a moderate one.",
     "Cannot affect tribulation outcomes or scripted story failures.", "stat", stat_bonuses={"cultivation_speed_pct": 0.03})

# -- Bracelets / belts / brooch (all share the single "bracelet" slot) ------------------------
_reg("acc_herb_scented_wrist_cord", "Herb-Scented Wrist Cord", "Accessory", "Bracelet", "Bracelet", 1, "Common",
     "Wood, Food", "Pills and healing consumables restore 5% more.",
     "Does not increase permanent-stat pills.", "stat", stat_bonuses={"essence_regen_pct": 0.02})
_reg("acc_iron_vine_bracer", "Iron-Vine Bracer", "Accessory", "Bracelet", "Bracelet", 2, "Rare",
     "Wood, Metal", "Blocking an attack grants 2% stacking defense for the encounter, up to 10%.",
     "Stacks are lost at encounter end.", "post_action_buff", {"trigger": "encounter_start", "def_pct": 0.06, "duration_seconds": 60})
_reg("acc_merchants_abacus_bracelet", "Merchant's Abacus Bracelet", "Accessory", "Bracelet", "Bracelet", 2, "Rare",
     "Information, Wealth", "NPC purchase prices are 4% lower and sale prices are 4% higher.",
     "Does not affect player trades, auctions, or fixed-price special shops.", "stat", stat_bonuses={"stone_reward_bonus_pct": 0.04})
_reg("acc_four_season_prayer_beads", "Four-Season Prayer Beads", "Accessory", "Bracelet", "Bracelet", 3, "Epic",
     "Time, Wood", "Changes one daily bonus based on the rotating season: cultivation, healing, gathering, or travel.",
     "Season changes at reset and cannot be manually selected.", "stat", stat_bonuses={"cultivation_speed_pct": 0.02, "essence_regen_pct": 0.02})
_reg("acc_beast_calming_waist_token", "Beast-Calming Waist Token", "Accessory", "Bracelet", "Belt Token", 3, "Rare",
     "Enslavement, Soul", "Reduces hostile beast encounter chance by 12% and improves taming checks by one minor grade.",
     "No effect on boss beasts or enraged story creatures.", "stat", stat_bonuses={"beast_damage_reduction_pct": 0.04})
_reg("acc_hundred_pocket_immortal_belt", "Hundred-Pocket Immortal Belt", "Accessory", "Bracelet", "Belt", 4, "Legendary",
     "Space, Refinement", "Adds 24 material-only inventory slots and automatically sorts materials by rank and path.",
     "Cannot store equipment, currency, living creatures, or quest objects.", "stat", stat_bonuses={"stone_reward_bonus_pct": 0.03})
_reg("acc_scarlet_tribulation_sash", "Scarlet Tribulation Sash", "Accessory", "Bracelet", "Belt", 5, "Mythic",
     "Blood, Lightning", "After surviving below 10% HP, gain a Tribulation Spark that grants +20% breakthrough success for the next attempt.",
     "Spark expires in 24 hours; cannot be intentionally triggered by self-damage outside combat.",
     "breakthrough_boost_daily", {"chance_pct": 0.20})
_reg("acc_brooch_of_shared_prosperity", "Brooch of Shared Prosperity", "Accessory", "Bracelet", "Brooch", 5, "Legendary",
     "Luck, Human", "When a party member obtains a Legendary-or-better drop, all other party members receive a small consolation cache.",
     "One cache per player per day; caches cannot contain Legendary or Unique items.", "stat", stat_bonuses={"stone_reward_bonus_pct": 0.06})


# ================================================================================================
# 8. ARTIFACT LOOT POOL
# ================================================================================================

# -- Gourds ------------------------------------------------------------------------------------
_reg("art_springwater_essence_gourd", "Springwater Essence Gourd", "Artifact", "Artifact", "Gourd", 1, "Common",
     "Water, Qi", "Stores three sips. Each sip restores 12% primeval essence outside combat.",
     "Refills at daily reset; cannot be used during breakthrough resolution.",
     "essence_restore_charges", {"charges": 3, "pct": 0.12})
_reg("art_hundred_herb_medicine_gourd", "Hundred-Herb Medicine Gourd", "Artifact", "Artifact", "Gourd", 2, "Uncommon",
     "Wood, Food", "Automatically brews one random low-rank healing draught from spare herbs each day.",
     "Consumes the herbs; cannot create permanent-stat pills.", "stat", stat_bonuses={"essence_regen_pct": 0.02})
_reg("art_miasma_swallowing_gourd", "Miasma-Swallowing Gourd", "Artifact", "Artifact", "Gourd", 2, "Rare",
     "Poison, Qi", "Absorbs one poison or miasma hazard and converts it into a poison charge for the next attack.",
     "Two charges per day; cannot absorb tribulation poison.", "encounter_shield", {"reduction_pct": 0.10, "hits": 2})
_reg("art_beast_spirit_wine_gourd", "Beast-Spirit Wine Gourd", "Artifact", "Artifact", "Gourd", 3, "Epic",
     "Food, Transformation", "Drink to gain one random beast trait — claws, hide, scent, or speed — for one encounter.",
     "Once per day; has a 10% chance to inflict a temporary beast temperament penalty.",
     "post_action_buff", {"trigger": "encounter_start", "str_pct": 0.08, "duration_seconds": 90})
_reg("art_fortune_pouring_golden_gourd", "Fortune-Pouring Golden Gourd", "Artifact", "Artifact", "Gourd", 4, "Legendary",
     "Luck, Wealth", "Before opening a chest, pour one Fortune measure to add an extra independent loot roll.",
     "One measure per day; extra roll cannot produce Unique, quest, or guaranteed drops.",
     "extra_loot_roll_daily", {})
_reg("art_two_moon_treasure_gourd", "Two-Moon Treasure Gourd", "Artifact", "Artifact", "Gourd", 5, "Mythic",
     "Luck, Space", "Once per day, choose one eligible loot result and create a second copy of it.",
     "Cannot copy Unique, bound, quest, pity-guaranteed, currency jackpot, or daily-limited items; copied item is account-bound for seven days.",
     "loot_duplicate_daily", {})
_reg("art_calamity_drinking_black_gourd", "Calamity-Drinking Black Gourd", "Artifact", "Artifact", "Gourd", 6, "Mythic",
     "Heaven, Dark", "Absorbs part of a tribulation's damage and stores Calamity Qi. Calamity Qi can empower cultivation or artifact attacks.",
     "Overfilling creates a backlash encounter; requires immortal essence upkeep.",
     "breakthrough_boost_daily", {"chance_pct": 0.15})
_reg("art_gourd_of_reversed_rivers", "Gourd of Reversed Rivers", "Artifact", "Artifact", "Gourd", 7, "Unique",
     "Water, Qi", "Once per day, fully restores the player's primeval essence.",
     "Once per day; cannot overfill essence.",
     "essence_restore_charges", {"charges": 1, "pct": 1.0})

# -- Flying Swords -------------------------------------------------------------------------------
_reg("art_green_bamboo_flying_sword", "Green Bamboo Flying Sword", "Artifact", "Artifact", "Flying Sword", 1, "Common",
     "Sword, Wood", "A reliable active attack with +8% accuracy against unarmored targets.",
     "Costs essence each use.", "stat", stat_bonuses={"atk_stat": 3})
_reg("art_returning_sparrow_sword", "Returning Sparrow Sword", "Artifact", "Artifact", "Flying Sword", 2, "Rare",
     "Sword, Wind", "After attacking, has a 25% chance to immediately return one-third of its essence cost.",
     "Refund can trigger once per turn.", "stat", stat_bonuses={"spd_stat": 3, "atk_stat": 2})
_reg("art_seven_shadow_pursuit_sword", "Seven-Shadow Pursuit Sword", "Artifact", "Artifact", "Flying Sword", 3, "Epic",
     "Sword, Shadow", "Creates up to seven shadow marks across repeated attacks. At seven marks, the next strike deals heavy bonus damage.",
     "Marks disappear if the target changes or the encounter ends.", "post_action_buff", {"trigger": "encounter_start", "atk_pct": 0.14, "duration_seconds": 60})
_reg("art_cloud_riding_courier_sword", "Cloud-Riding Courier Sword", "Artifact", "Artifact", "Flying Sword", 3, "Rare",
     "Sword, Cloud, Information", "Reduces travel time and can deliver one item or message to another player remotely each day.",
     "Cannot deliver bound, living, stolen, or quest items.", "clue_chance",
     stat_bonuses={"search_recharge_reduction_pct": 0.05})
_reg("art_blood_returning_execution_sword", "Blood-Returning Execution Sword", "Artifact", "Artifact", "Flying Sword", 4, "Legendary",
     "Sword, Blood", "Defeating an enemy with the sword restores 10% missing HP and 8% missing essence.",
     "Triggers once per encounter; no benefit from trivial enemies.", "stat", stat_bonuses={"lifesteal_percent": 0.05})
_reg("art_sky_splitting_formation_sword", "Sky-Splitting Formation Sword", "Artifact", "Artifact", "Flying Sword", 5, "Mythic",
     "Sword, Formation", "Can anchor a three-point sword formation. Each allied formation sword increases group damage and defense.",
     "Requires three distinct players or three compatible sword spirits; one formation per party.",
     "post_action_buff", {"trigger": "encounter_start", "str_pct": 0.08, "def_pct": 0.08})
_reg("art_dao_mark_severing_sword", "Dao-Mark Severing Sword", "Artifact", "Artifact", "Flying Sword", 6, "Mythic",
     "Sword, Rule", "Temporarily suppresses a portion of an enemy's strongest path bonus after three consecutive hits.",
     "Boss suppression is heavily reduced; costs immortal essence.", "post_action_buff", {"trigger": "encounter_start", "atk_pct": 0.10, "duration_seconds": 60})
_reg("art_sword_before_it_leaves", "Sword That Returns Before It Leaves", "Artifact", "Artifact", "Flying Sword", 7, "Unique",
     "Sword, Time", "The first sword attack each encounter resolves twice: once normally and once as a weaker time echo.",
     "The echo cannot trigger on-hit loops, execute effects, or additional echoes.",
     "unique_signature", {"handler": "echo_sword"})

# -- Mirrors, lamp, lantern, bell ------------------------------------------------------------
_reg("art_dust_revealing_bronze_mirror", "Dust-Revealing Bronze Mirror", "Artifact", "Artifact", "Mirror", 1, "Uncommon",
     "Light, Information", "Reveals whether a discovered room contains a trap, creature, treasure, or illusion.",
     "Shows category only, not exact contents.", "clue_chance", {}, stat_bonuses={"clue_chance_bonus_pct": 0.02})
_reg("art_soul_reflection_mirror", "Soul-Reflection Mirror", "Artifact", "Artifact", "Mirror", 3, "Epic",
     "Soul, Wisdom", "Once per day, reflect one fear, charm, or confusion effect back at its source.",
     "Does not reflect tribulation or area-wide effects.", "encounter_shield", {"reduction_pct": 0.12, "hits": 1})
_reg("art_broken_fate_mirror", "Broken Fate Mirror", "Artifact", "Artifact", "Mirror", 5, "Mythic",
     "Luck, Wisdom", "After seeing a failed non-combat roll, shatter one stored mirror fragment to reroll it.",
     "Stores one fragment per week; second result is final; cannot reroll drops or breakthroughs.",
     "search_reroll_daily", {"weekly": True})
_reg("art_corpse_flame_soul_lamp", "Corpse-Flame Soul Lamp", "Artifact", "Artifact", "Lamp", 2, "Rare",
     "Soul, Fire", "Captures faint soul embers from defeated enemies, which can be spent to identify items or fuel soul-path crafting.",
     "Daily capture cap; no souls from players or protected NPCs.", "stat", stat_bonuses={"stone_reward_bonus_pct": 0.03})
_reg("art_everbright_inheritance_lantern", "Everbright Inheritance Lantern", "Artifact", "Artifact", "Lantern", 4, "Legendary",
     "Light, Information", "Within an inheritance, reveals one optional room and reduces the chance of choosing a dead end.",
     "One reveal per inheritance; some hidden rooms resist detection.", "clue_chance", {}, stat_bonuses={"clue_chance_bonus_pct": 0.05})
_reg("art_bell_of_the_last_warning", "Bell of the Last Warning", "Artifact", "Artifact", "Bell", 5, "Mythic",
     "Sound, Time", "Rings automatically before lethal damage, giving the player one emergency action before the damage resolves.",
     "Once per day; the emergency action cannot directly kill the attacker or use another death-prevention effect.",
     "defeat_ward_daily", {})

# -- Fans, umbrellas, boats -------------------------------------------------------------------
_reg("art_five_winds_folding_fan", "Five-Winds Folding Fan", "Artifact", "Artifact", "Fan", 3, "Epic",
     "Wind", "Select one stance per encounter: speed, evasion, knockback, projectile deflection, or travel.",
     "Stance cannot be changed during the encounter.", "post_action_buff", {"trigger": "encounter_start", "spd_pct": 0.10, "duration_seconds": 60})
_reg("art_fan_of_scattered_calamity", "Fan of Scattered Calamity", "Artifact", "Artifact", "Fan", 6, "Mythic",
     "Wind, Heaven", "Redistributes a portion of one large incoming attack across the next five turns.",
     "Total damage is not reduced; cannot redistribute instant-death scripted effects.",
     "encounter_shield", {"reduction_pct": 0.10, "hits": 5})
_reg("art_iron_shell_protection_umbrella", "Iron-Shell Protection Umbrella", "Artifact", "Artifact", "Umbrella", 2, "Rare",
     "Metal, Defense", "Open to reduce ranged damage by 18% for three enemy actions.",
     "Once per encounter; movement is reduced while open.", "encounter_shield", {"reduction_pct": 0.18, "hits": 3})
_reg("art_rain_calling_azure_umbrella", "Rain-Calling Azure Umbrella", "Artifact", "Artifact", "Umbrella", 4, "Legendary",
     "Water, Cloud", "Creates rain for one encounter, empowering water and lightning effects while weakening fire effects.",
     "Once per day; affects allies and enemies equally.", "post_action_buff", {"trigger": "encounter_start", "atk_pct": 0.08, "duration_seconds": 90})
_reg("art_cloud_sailing_leaf_boat", "Cloud-Sailing Leaf Boat", "Artifact", "Artifact", "Boat", 3, "Rare",
     "Wood, Cloud", "Party travel is 15% faster and random travel encounters are 10% less frequent.",
     "Benefits up to four players; no effect inside sealed realms.", "clue_chance",
     stat_bonuses={"search_recharge_reduction_pct": 0.08})
_reg("art_void_crossing_bone_boat", "Void-Crossing Bone Boat", "Artifact", "Artifact", "Boat", 6, "Mythic",
     "Space, Bone", "Opens a short-lived route to a previously visited region or secret-realm entrance.",
     "Once every three days; high immortal essence cost; cannot bypass story locks.",
     "search_reroll_daily", {})

# -- Cauldrons, pagoda, incense burner, seal, banner, hourglass, compass, scale ---------------
_reg("art_nine_embers_refinement_cauldron", "Nine-Embers Refinement Cauldron", "Artifact", "Artifact", "Cauldron", 4, "Legendary",
     "Fire, Refinement", "Refining with nine different compatible materials grants a bonus chance to preserve one consumed rare material.",
     "One preservation per refinement; cannot preserve the main recipe core.", "salvage_bonus", {"pct": 0.15})
_reg("art_heaven_and_earth_resonance_cauldron", "Heaven-and-Earth Resonance Cauldron", "Artifact", "Artifact", "Cauldron", 6, "Mythic",
     "Refinement, Heaven", "Once per week, upgrades a failed refinement into a flawed but usable result instead of destroying it.",
     "Flawed results gain a permanent drawback and cannot be sold to NPCs.", "salvage_bonus", {"pct": 0.30, "weekly": True})
_reg("art_six_layer_defense_pagoda", "Six-Layer Defense Pagoda", "Artifact", "Artifact", "Pagoda", 5, "Mythic",
     "Earth, Formation", "Generates six defensive layers. Each heavy hit breaks one layer and reduces that hit substantially.",
     "Layers refill at daily reset; only one layer can break per enemy action.", "encounter_shield", {"reduction_pct": 0.20, "hits": 6})
_reg("art_dream_wandering_incense_burner", "Dream-Wandering Incense Burner", "Artifact", "Artifact", "Incense Burner", 4, "Legendary",
     "Dream, Soul", "Spend incense to enter a short training dream that grants temporary skill proficiency or lore clues.",
     "Two uses per day; repeated use can cause Dream Fatigue.", "essence_restore_charges", {"charges": 2, "pct": 0.10})
_reg("art_seal_of_the_silent_command", "Seal of the Silent Command", "Artifact", "Artifact", "Seal", 5, "Legendary",
     "Rule, Enslavement", "Imposes one simple command on a weakened non-boss creature: halt, flee, release, or reveal.",
     "Once per encounter; targets may resist based on soul strength.", "encounter_shield", {"reduction_pct": 0.10, "hits": 2})
_reg("art_banner_of_shared_killing_intent", "Banner of Shared Killing Intent", "Artifact", "Artifact", "Banner", 5, "Mythic",
     "Human, Killing", "Party members gain escalating damage against the same boss after each full round without a member being defeated.",
     "Bonus resets when a party member falls or changes target.", "post_action_buff",
     {"trigger": "encounter_start", "atk_pct": 0.10, "duration_seconds": 90})
_reg("art_hourglass_of_borrowed_dawn", "Hourglass of Borrowed Dawn", "Artifact", "Artifact", "Hourglass", 6, "Mythic",
     "Time", "Once per week, immediately refresh one ordinary daily search, travel, or gathering charge.",
     "Cannot refresh death wards, drop duplication, breakthroughs, tribulations, or other weekly effects.",
     "refresh_artifact_weekly", {"weekly": True})
_reg("art_treasure_summoning_compass", "Treasure-Summoning Compass", "Artifact", "Artifact", "Compass", 4, "Legendary",
     "Information, Luck", "Choose materials, Gu, manuals, accessories, or artifacts before a search; matching discoveries are 15% more likely.",
     "Does not change rarity; one category choice per day.", "clue_chance", {}, stat_bonuses={"clue_chance_bonus_pct": 0.06})
_reg("art_scale_of_equal_exchange", "Scale of Equal Exchange", "Artifact", "Artifact", "Scale", 6, "Unique",
     "Rule, Wealth", "Once per week, sacrifice several same-rank items to generate one random item of a selected category and equal total value.",
     "Cannot generate Unique items; sacrificed bound items produce a bound result.",
     "unique_signature", {"handler": "scale_of_exchange"})


# -- Verdant Borderlands / Qi Condensation (content expansion brief sections 16-17) ------------
# All rank 1, matching the region's other content (hunt monsters/Gu families/manual pages are
# all "Rank 1" or "drop_rank 1" too). Reachable the same way every OTHER item in this catalog
# already is — accessories_gen.roll_accessory_or_artifact filters by rank/rarity generically,
# so nothing extra needs wiring into hunt.py/discovery_gen.py for these to start dropping.
# "paths" is chosen to match this session's own Verdant Borderlands discovery theme tags
# exactly where the brief's own source ties to one (Moonwell Earring <-> Moon Rabbit Hidden
# Burrow, Packlord Fang Necklace <-> Blood Fang Hunter's Inheritance, Grave Lantern <-> Grave
# Moss Hermit's Cave/Hollow Grave Descent/The Gravekeeper's Long Watch) — so completing one of
# those now actually path-weights toward the matching item via _path_weight's tag intersection.
#
# Two brief-described mechanics were adapted rather than built fresh, per this file's own
# adaptation-notes precedent at the top: Packlord Fang Necklace's "gains a Hunt Mark after
# defeating a wolf-type elite, capped" state-tracking was folded into an always-on, already-
# capped stat instead of new per-item state machinery (the brief's own MECHANIC_COST_GUIDE
# reserves stateful "unique_signature" tracking for Rank 6+, not a Rank 1 item); Poison-
# Drinking Gourd's "consume an approved venom item for the buff" input requirement was
# dropped in favor of the same no-cost daily post_action_buff every other low-rank artifact
# in this file already uses.
_reg("acc_ironhide_tusk_ring", "Ironhide Tusk Ring", "Accessory", "Ring", "Ring", 1, "Common",
     "Strength, Earth", "Gain +3% beast damage reduction. At the start of a fight, gain +12% DEF for 90 seconds.",
     "The DEF buff doesn't stack with a second copy.", "post_action_buff",
     {"trigger": "encounter_start", "def_pct": 0.12, "duration_seconds": 90},
     stat_bonuses={"beast_damage_reduction_pct": 0.03})
_reg("acc_moonwell_earring", "Moonwell Earring", "Accessory", "Earring", "Earring", 1, "Uncommon",
     "Moon, Luck", "+6% chance to notice hidden search leads, plus a touch of moonlit luck.",
     "Detection reveals a lead but doesn't guarantee finding it.", "clue_chance", {},
     stat_bonuses={"clue_chance_bonus_pct": 0.03, "luck_stat": 2})
_reg("acc_packlord_fang_necklace", "Packlord Fang Necklace", "Accessory", "Necklace", "Necklace", 1, "Rare",
     "Blood, Strength", "+6 ATK while below 50% HP, channeling the pack's own hunting instinct.",
     "Does not stack with a second copy.", "stat", stat_bonuses={"low_hp_atk_bonus": 6, "str_stat": 2})
_reg("acc_spider_silk_ring", "Spider-Silk Ring", "Accessory", "Ring", "Ring", 1, "Uncommon",
     "Poison, Movement", "+4% dodge chance, but -8 max HP — moving like something that isn't quite solid always costs a little something.",
     "The HP penalty is permanent while equipped; there's no way to keep the dodge without it.",
     "stat", stat_bonuses={"dodge_chance_pct": 0.04, "hp": -8})
_reg("art_poison_drinking_gourd", "Poison-Drinking Gourd", "Artifact", "Artifact", "Gourd", 1, "Rare",
     "Poison, Water", "Once per fight, exude a numbing venom that shields you from the first strikes — +15% DEF for 90 seconds after the fight begins.",
     "The shield expires after 90 seconds regardless of what's still fighting you.", "post_action_buff",
     {"trigger": "encounter_start", "def_pct": 0.15, "duration_seconds": 90}, stat_bonuses={"hp": 8})
_reg("art_grave_lantern", "Grave Lantern", "Artifact", "Artifact", "Lantern", 1, "Rare",
     "Soul, Earth", "Once per day, when you'd be struck down, the lantern flares and wards away the loss instead.",
     "Once per daily reset, same as any other defeat ward — doesn't stack with a second one equipped.",
     "defeat_ward_daily", {}, stat_bonuses={"deviation_resistance_pct": 0.03})

# -- Hundred Beast Mountains / Foundation Establishment (content expansion brief sections
# 6.1/7.2/17) — rank 2, matching this region's hunt monsters/Gu families. Thunderhorn War
# Drum is the Thunderhorn Herd Tyrant raid's own named signature reward per the brief's own
# section 6.1 write-up ("Signature rare reward: Thunderhorn War Drum artifact") — like every
# other item in this catalog it's reached purely through the generic rank/rarity roll
# (raid.py already calls roll_and_grant_accessory_artifact on every raid win), NOT a
# monster.drops DropEntry — accessories/artifacts are tracked as their own
# accessory_artifact_instances, not generic inventory items, so they can never be a plain
# DropEntry the way a material or crafted-gear reward is.
#
# The brief describes this as a "party STR or SPD buff" — but "raid_party_bonus" (at the time
# this comment was written, used by four PRE-EXISTING items: Golden Thread Karma Necklace,
# Brooch of Shared Prosperity, Sky-Splitting Formation Sword, Banner of Shared Killing Intent)
# turned out to be a dead effect_key: it was recognized/displayable and listed in
# MECHANIC_COST_GUIDE, but nothing in manager.py or raid.py ever actually read it — a
# pre-existing gap from this system's original build. Rather than add a FIFTH item onto a
# demonstrably non-functional mechanic, this uses post_action_buff instead (already real,
# already tested) — an honest scope-down from "whole party" to "just the activator", which is
# what post_action_buff can actually deliver. All four of those pre-existing items were
# themselves converted off raid_party_bonus for the same reason on 2026-08-13 (2 to "stat",
# 2 to this same post_action_buff self-only pattern) — see each item's own registration below
# and MECHANIC_COST_GUIDE's own note above; raid_party_bonus has no items using it anymore.
_reg("art_thunderhorn_war_drum", "Thunderhorn War Drum", "Artifact", "Artifact", "Drum", 2, "Rare",
     "Lightning, Strength", "Beat the drum at the start of a fight to grant yourself +10% STR and +6% SPD for its duration.",
     "Long cooldown; the buff doesn't stack with a second Thunderhorn War Drum.",
     "post_action_buff", {"trigger": "encounter_start", "str_pct": 0.10, "spd_pct": 0.06, "duration_seconds": 90})

# Ghost Eye Pendant / Thunderhorn Torque (brief's own "## Foundation accessories" list,
# section 16) — both use the same honest scope-down as Thunderhorn War Drum above: the
# brief's "expose a boss weakness" (party-wide) and "bonus to empowered attacks" (would need
# a new combat hook to actually detect an Empower-flagged hit inside combat.resolve_attack)
# aren't cleanly buildable on existing mechanics, so both lean on a real passive stat plus a
# real self-only post_action_buff instead of promising something that doesn't work.
_reg("acc_ghost_eye_pendant", "Ghost Eye Pendant", "Accessory", "Necklace", "Necklace", 2, "Rare",
     "Soul, Wisdom, Strength", "+4% crit chance. At the start of a fight, gain +10% ATK for its duration as the pendant reveals an opening.",
     "The ATK buff doesn't stack with a second copy.", "post_action_buff",
     {"trigger": "encounter_start", "atk_pct": 0.10, "duration_seconds": 90}, stat_bonuses={"crit_chance_pct": 0.04})
_reg("acc_thunderhorn_torque", "Thunderhorn Torque", "Accessory", "Necklace", "Necklace", 2, "Rare",
     "Lightning, Strength", "+5% physical damage. At the start of a fight, gain a further +8% ATK for its duration, as if charged up for an empowered strike.",
     "The activated bonus doesn't stack with a second copy.", "post_action_buff",
     {"trigger": "encounter_start", "atk_pct": 0.08, "duration_seconds": 90}, stat_bonuses={"physical_damage_pct": 0.05})

# Furnace Master's Thumb Ring / Star-Iron Stomach Belt / Crimson Furnace Cauldron (brief's
# own "## Core accessories" list, section 16, plus its own artifact section 17.4) — rank 3,
# matching this region's hunt monsters/Gu families. Alchemy success chance and material-
# salvage chance are both REAL mechanics now (see GameManager.craft_pill /
# _alchemy_salvage_bonus_pct), wired specifically to make these two items and Crimson Furnace
# Cauldron actually do what they say — alchemy_success_pct is a brand new SPECIAL_BONUS_KEY,
# and salvage_bonus (previously a dead effect_key used only by two PRE-EXISTING items, Nine-
# Embers Refinement Cauldron and Heaven-and-Earth Resonance Cauldron, neither of which was
# ever actually read anywhere) is now real too, fixing those two as a side effect. Both are
# clamped/capped at the point of use (craft_pill's own min(1.0, ...) on chance, plus
# professions.craft_success_chance's own realistic per-rank range), so neither can make
# failure literally impossible at low Alchemist rank, matching the brief's own caution.
_reg("acc_furnace_masters_thumb_ring", "Furnace Master's Thumb Ring", "Accessory", "Ring", "Ring", 3, "Rare",
     "Fire, Refinement", "+8% alchemy success chance.",
     "Cannot push success chance to 100% on its own — Alchemist rank still matters.",
     "stat", stat_bonuses={"alchemy_success_pct": 0.08})
_reg("acc_star_iron_stomach_belt", "Star-Iron Stomach Belt", "Accessory", "Bracelet", "Belt", 3, "Rare",
     "Metal, Space", "+5% loot chance and +4% Spirit Stone rewards.",
     "Does not increase drop rarity, only frequency.", "stat",
     stat_bonuses={"loot_chance_bonus_pct": 0.05, "stone_reward_bonus_pct": 0.04})
_reg("art_crimson_furnace_cauldron", "Crimson Furnace Cauldron", "Artifact", "Artifact", "Cauldron", 3, "Epic",
     "Fire, Refinement", "+10% alchemy success chance. 20% chance any alchemy craft refunds one of its consumed herbs.",
     "The herb refund is independent per craft — it can trigger on a failed brew too.",
     "salvage_bonus", {"pct": 0.20}, stat_bonuses={"alchemy_success_pct": 0.10})

# -- Convenience lookups -------------------------------------------------------------------------
ACCESSORY_ITEMS = {k: v for k, v in ITEMS.items() if v.category == "Accessory"}
ARTIFACT_ITEMS = {k: v for k, v in ITEMS.items() if v.category == "Artifact"}
ITEMS_BY_SLOT_TYPE: Dict[str, List[Affix]] = {}
for _item in ITEMS.values():
    ITEMS_BY_SLOT_TYPE.setdefault(_item.slot_type, []).append(_item)


# ================================================================================================
# 9. OPTIONAL SET BONUSES
# ================================================================================================
@dataclass
class SetBonus:
    set_id: str
    name: str
    item_ids: List[str]
    bonus_2pc: str
    bonus_3pc: Optional[str]
    stat_bonuses_2pc: Dict[str, float] = field(default_factory=dict)
    stat_bonuses_3pc: Dict[str, float] = field(default_factory=dict)


SET_BONUSES: Dict[str, SetBonus] = {
    "twin_fortune_regalia": SetBonus(
        "twin_fortune_regalia", "Twin Fortune Regalia",
        ["acc_twin_fortune_rings", "acc_golden_thread_karma_necklace"],
        "+5% cooperative loot luck.", "Once per week, a party chest with no Rare-or-better item gains one guaranteed Rare item.",
        stat_bonuses_2pc={"loot_chance_bonus_pct": 0.05},
    ),
    "cloud_wanderer": SetBonus(
        "cloud_wanderer", "Cloud Wanderer Set",
        ["acc_cloud_step_talisman_necklace", "acc_swallow_tail_earrings", "art_cloud_sailing_leaf_boat"],
        "+8% travel speed (search recharge).", "First failed movement/search reroll each day is free.",
        stat_bonuses_2pc={}, stat_bonuses_3pc={},
    ),
    "last_breath": SetBonus(
        "last_breath", "Last Breath Set",
        ["acc_life_retaining_vermilion_ring", "art_bell_of_the_last_warning", "acc_nine_deaths_black_pearl"],
        "Death-prevention penalties are reduced by 20%.", "After a death-prevention trigger, deal 15% less damage for the rest of the encounter (prevents infinite safety builds).",
    ),
    "ancient_inheritor": SetBonus(
        "ancient_inheritor", "Ancient Inheritor Set",
        ["art_everbright_inheritance_lantern", "acc_whisper_of_ancient_intent", "acc_ancestors_sealed_locket"],
        "+10% inheritance clue quality.", "Gain one extra choice after completing an inheritance trial, but one choice is cursed.",
        stat_bonuses_2pc={"loot_chance_bonus_pct": 0.04},
    ),
    "refiners_ninefold": SetBonus(
        "refiners_ninefold", "Refiner's Ninefold Set",
        ["art_nine_embers_refinement_cauldron", "acc_herb_scented_wrist_cord", "acc_hundred_pocket_immortal_belt"],
        "+5% refining success.", "First ordinary refinement failure each day returns 25% of common materials.",
    ),
}
