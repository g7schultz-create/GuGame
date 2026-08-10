"""
Static content for character creation (/join): races, cultivation roots,
physiques, and cultivation paths.

`stat_bonuses` on each entry is the machine-usable subset of its bonuses —
only keys with a real system behind them:
    str_pct, hp_pct, spd_pct, def_pct, qi_pct, luck_flat   (foundation stats, applied once at /join confirm)
    cultivation_speed_pct, qi_recovery_pct                 (both just feed the qi accrual rate — see chargen.effective_qi_rate_bonus)
    breakthrough_chance_pct                                (feeds chargen.effective_breakthrough_chance)
    dao_comprehension_pct                                  (chance/size of bonus qi refund on a successful breakthrough — also
                                                              how Righteous's "bonus cultivation on breakthrough" passive is wired up)
A handful of `passive` texts also now have a real mechanic behind them, hooked
in directly by name (race == "Rockman"/physique_tier == "Rare"/"Mythic"/"Epic")
rather than through stat_bonuses, since they're conditional/combat-time rather
than flat modifiers — see chargen.race_physique_damage_reduction (Rockman,
Rare Physique), GameDatabase.try_use_daily_fatal_hit_negation (Mythic
Physique), and GameManager.attempt_breakthrough's Epic Physique buff grant.
Rogue's "hidden inheritances/secret realms/..." passive is folded into
/explore's odds via GameManager.ROGUE_EXPLORE_LUCK_BONUS.
Everything else described in `display_bonuses`/`passive` (Gu refinement,
tribulation success, reputation, sect contribution, shop prices, Demonic's
Blood Essence economy, the ~25 per-name Unique-tier passives referencing
things like "Ice Path"/"Soul Path" techniques...) is still flavor/display
only — those systems don't exist yet.
"Main Stat" on physiques is assumed to mean STR — there's no other stat
singled out as a physique's "main" stat in the source material.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Race:
    name: str
    tagline: str
    display_bonuses: List[str]
    passive: str
    stat_bonuses: Dict[str, float] = field(default_factory=dict)


@dataclass
class Tier:
    name: str
    emoji: str
    display_bonuses: List[str]
    names: List[str]
    passive: Optional[str] = None
    stat_bonuses: Dict[str, float] = field(default_factory=dict)
    unique_passives: Optional[Dict[str, str]] = None


@dataclass(frozen=True)
class CharacterTraitSpec:
    """A single named root's (eventually: named physique's) OWN mechanic, layered on top of
    its shared ROOT_TIERS package (see ROOT_SPECS_BY_NAME below) — this is what makes e.g.
    Wood Root and Fire Root actually play differently instead of being reskins of the same
    Common-tier numbers. Deliberately the same "just a stat_bonuses dict" shape every other
    bonus source in this file already uses (Race/Tier/Path), so chargen._total_bonus and
    GameManager.compute_equipment_bonuses can treat a spec as just one more source to sum —
    no new plumbing, no scattered `if root_name == "..."` checks anywhere else in the codebase.

    stat_bonuses keys used by roots (all real, all consumed somewhere — see each key's own
    consumer for where):
      herb_yield_pct, mining_yield_pct        -- GameManager.start_gathering_patch/
                                                   start_mining_vein/harvest_farm_plot
      healing_item_pct                        -- GameManager.use_item (healing items only)
      essence_regen_pct, alchemy_success_pct,
      clue_chance_bonus_pct, insight_gain_pct -- pre-existing SPECIAL_BONUS_KEYS, now also
                                                   fed by compute_equipment_bonuses' root fold-in
      blacksmith_success_pct                  -- GameManager.craft_gear
      gear_dismantle_refund_pct               -- GameManager.dismantle_crafted_gear
      meditate_qi_pct, meditate_battle_qi_pct -- GameManager.meditate
      breakthrough_qi_loss_reduction_pct      -- GameManager.attempt_breakthrough (folds into
                                                   the same deviation_resistance a manual uses)
      explore_luck_bonus_flat                 -- GameManager.start_exploration_hunt (extra
                                                   effective luck, same trick Rogue's path
                                                   passive already uses)
      flee_chance_flat                        -- hunt.py/raid.py flee-chance calc
      empower_damage_pct                      -- hunt.py/raid.py Empowered Attack damage

    manual_coherence_tags/manual_coherence_categories: preview-coherence bonus (see
    manual_gen.calculate_coherence's bonus_tags/bonus_categories params) for any page whose
    tags/category match — capped per-spec at MANUAL_COHERENCE_BONUS_CAP so no single root can
    blow past the design brief's own combined root+physique coherence budget (section 4.1;
    physiques don't contribute yet, so the full cap is available to a root alone for now).
    manual_coherence_flat is the same budget's untargeted cousin — applies to EVERY page
    regardless of tag/category match (Primordial Origin Root's "all manual paths gain +5
    preview coherence"), also subject to the same cap.

    fire_battle_qi_str_bonus_pct/fire_battle_qi_trigger_fraction: Fire family's one stateful
    trigger ("after spending 30% battle Qi in one encounter, gain +3% STR for the next
    attack") — kept as its own pair of fields rather than a generic stat_bonuses key since
    it's genuinely an encounter-scoped trigger, not a flat modifier; see hunt.py/raid.py's
    _fire_root_str_bonus handling.

    daily_nothing_upgrade: Void Star Root's one boolean daily charge ("once daily, a search
    that would give nothing is upgraded to a minor find") — see GameDatabase.
    try_use_daily_search_upgrade / GameManager.run_search's "nothing" branch.

    skip_path_settling_penalty: Sovereign Immortal Root's Unique mechanic — see
    GameManager.change_cultivation_path.

    Every OTHER Unique root's own bespoke mechanic (Section 8 of the design brief — each one
    is a genuinely one-off named rule, not a reusable family) is implemented as a targeted
    `root_spec.name == "..."` check localized to the single function that owns that mechanic
    (e.g. raid.py's _on_victory owns Giant Sun Inheritor Root's Connect Luck), rather than
    adding a dozen more single-use fields here. This is a deliberate, narrow exception to
    "never check root name directly" — Unique mechanics are 1-to-1 with one specific root by
    design, unlike the shared elemental families every other tier uses.
    """

    trait_id: str
    name: str
    tier: str
    tags: tuple = ()
    description: str = ""
    stat_bonuses: Dict[str, float] = field(default_factory=dict)
    manual_coherence_tags: Dict[str, int] = field(default_factory=dict)
    manual_coherence_categories: Dict[str, int] = field(default_factory=dict)
    manual_coherence_flat: int = 0
    fire_battle_qi_str_bonus_pct: float = 0.0
    fire_battle_qi_trigger_fraction: float = 0.0
    daily_nothing_upgrade: bool = False
    skip_path_settling_penalty: bool = False


MANUAL_COHERENCE_BONUS_CAP = 20  # see CharacterTraitSpec docstring — design brief section 4.1


@dataclass
class Path:
    name: str
    tagline: str
    display_bonuses: List[str]
    passive_name: str
    passive_text: str
    weakness: str
    stat_bonuses: Dict[str, float] = field(default_factory=dict)


RACES: Dict[str, Race] = {
    "Human": Race(
        name="Human",
        tagline="Heaven's favored race, adaptable in all things.",
        display_bonuses=[
            "🌿 Cultivation Speed: +12%",
            "⭐ Breakthrough Chance: +8%",
            "🍀 Luck: +5",
            "📖 Aptitude Experience Gain: +15%",
        ],
        passive="Every breakthrough grants +1 random permanent stat (STR, ATK, HP, SPD, DEF, QI, or LCK).",
        stat_bonuses={"cultivation_speed_pct": 0.12, "luck_flat": 5, "breakthrough_chance_pct": 0.08},
    ),
    "Hairy Man": Race(
        name="Hairy Man",
        tagline="The unrivaled refiners of the Gu world.",
        display_bonuses=[
            "🌿 Cultivation Speed: +5%",
            "⭐ Breakthrough Chance: +5%",
            "🔨 Gu Refinement Success: +30%",
            "💎 Resource Yield: +15%",
        ],
        passive="Failed Gu refinements refund 50% of the materials.",
        stat_bonuses={"cultivation_speed_pct": 0.05, "breakthrough_chance_pct": 0.05},
    ),
    "Rockman": Race(
        name="Rockman",
        tagline="Their bodies rival mountains.",
        display_bonuses=[
            "🌿 Cultivation Speed: +4%",
            "⭐ Breakthrough Chance: +12%",
            "❤️ HP: +20%",
            "🛡️ DEF: +20%",
        ],
        passive="Receive 15% less damage while above 50% HP.",
        stat_bonuses={"cultivation_speed_pct": 0.04, "hp_pct": 0.20, "def_pct": 0.20, "breakthrough_chance_pct": 0.12},
    ),
    "Snowman": Race(
        name="Snowman",
        tagline="Born in eternal frost, calm and enduring.",
        display_bonuses=[
            "🌿 Cultivation Speed: +15%",
            "⭐ Breakthrough Chance: +5%",
            "💧 QI: +15%",
            "💧 Qi Recovery: +20%",
        ],
        passive="Meditation restores 25% more Qi and grants a small chance to ignore negative status effects.",
        stat_bonuses={"cultivation_speed_pct": 0.15, "qi_pct": 0.15, "breakthrough_chance_pct": 0.05, "qi_recovery_pct": 0.20},
    ),
    "Inkman": Race(
        name="Inkman",
        tagline="Knowledge is the greatest weapon.",
        display_bonuses=[
            "🌿 Cultivation Speed: +8%",
            "⭐ Breakthrough Chance: +15%",
            "🍀 Luck: +10",
            "📚 Dao Comprehension Gain: +20%",
        ],
        passive="Every successful breakthrough has a 20% chance to immediately gain bonus cultivation progress toward the next stage.",
        stat_bonuses={"cultivation_speed_pct": 0.08, "luck_flat": 10, "breakthrough_chance_pct": 0.15, "dao_comprehension_pct": 0.20},
    ),
}


ROOT_TIER_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic", "Divine", "Unique"]

# Relative weights for rolling a tier — deliberately steep so the top end is
# "very very very rare". Tune freely; Unique is further gated by availability.
ROOT_TIER_WEIGHTS = {
    "Common": 5000,
    "Uncommon": 2700,
    "Rare": 1300,
    "Epic": 600,
    "Legendary": 250,
    "Mythic": 100,
    "Divine": 40,
    "Unique": 10,
}

ROOT_TIERS: Dict[str, Tier] = {
    "Common": Tier(
        name="Common",
        emoji="🟢",
        display_bonuses=["🌿 Cultivation Speed: +2%", "⭐ Breakthrough Chance: +1%"],
        stat_bonuses={"cultivation_speed_pct": 0.02, "breakthrough_chance_pct": 0.01},
        names=[
            "Wood Root", "Fire Root", "Water Root", "Earth Root", "Metal Root",
            "Wind Root", "Moon Root", "Stone Root", "River Root", "Forest Root",
            "Ash Root", "Cloud Root", "Mist Root", "Sand Root", "Lightning Spark Root",
        ],
    ),
    "Uncommon": Tier(
        name="Uncommon",
        emoji="🔵",
        display_bonuses=["🌿 Cultivation Speed: +5%", "⭐ Breakthrough Chance: +3%"],
        stat_bonuses={"cultivation_speed_pct": 0.05, "breakthrough_chance_pct": 0.03},
        names=[
            "Dual Wood-Fire Root", "Dual Water-Earth Root", "Dual Metal-Wind Root", "Storm Root",
            "Mountain Root", "Jade Root", "Deep Sea Root", "Wild Vine Root", "Thunder Root",
            "Crystal Root", "Blooming Lotus Root", "Flowing River Root", "Ironwood Root",
            "Glacial Root", "Golden Sand Root",
        ],
    ),
    "Rare": Tier(
        name="Rare",
        emoji="🟣",
        display_bonuses=["🌿 Cultivation Speed: +10%", "⭐ Breakthrough Chance: +6%"],
        passive="+5% Qi Recovery",
        stat_bonuses={"cultivation_speed_pct": 0.10, "breakthrough_chance_pct": 0.06, "qi_recovery_pct": 0.05},
        names=[
            "Three Element Root", "Azure Dragon Root", "White Tiger Root", "Vermillion Bird Root",
            "Black Tortoise Root", "Starfire Root", "Void Root", "Ancient Tree Root",
            "Ocean Heart Root", "Spirit Flame Root", "Heavenly Thunder Root", "Emerald Forest Root",
            "Mountain Vein Root", "Silver Moon Root", "Golden Sun Root",
        ],
    ),
    "Epic": Tier(
        name="Epic",
        emoji="🟠",
        display_bonuses=["🌿 Cultivation Speed: +15%", "⭐ Breakthrough Chance: +10%"],
        passive="+10% Qi Recovery, +5 Luck",
        stat_bonuses={"cultivation_speed_pct": 0.15, "luck_flat": 5, "breakthrough_chance_pct": 0.10, "qi_recovery_pct": 0.10},
        names=[
            "Heavenly Spirit Root", "Nine Rivers Root", "Ten Thousand Mountain Root",
            "Primordial Lightning Root", "Void Star Root", "Nether Flame Root", "Ancient Sea Root",
            "World Tree Root", "Celestial Wind Root", "Earth Core Root", "Heaven Vein Root",
            "Immortal Spring Root", "Dragon Vein Root", "Phoenix Vein Root",
        ],
    ),
    "Legendary": Tier(
        name="Legendary",
        emoji="🟡",
        display_bonuses=["🌿 Cultivation Speed: +22%", "⭐ Breakthrough Chance: +15%"],
        passive="+10 Luck, +10% Qi Recovery, +5% Dao Comprehension",
        stat_bonuses={
            "cultivation_speed_pct": 0.22, "luck_flat": 10, "breakthrough_chance_pct": 0.15,
            "qi_recovery_pct": 0.10, "dao_comprehension_pct": 0.05,
        },
        names=[
            "Heavenly Dao Root", "Earth Mother Root", "Primordial Origin Root", "Chaos Root",
            "Celestial River Root", "Infinite Sky Root", "Great Wilderness Root", "Genesis Root",
            "Heavenly Furnace Root", "Immortal Sovereign Root", "Star Sea Root", "Divine Dragon Root",
        ],
    ),
    "Mythic": Tier(
        name="Mythic",
        emoji="🔴",
        display_bonuses=["🌿 Cultivation Speed: +30%", "⭐ Breakthrough Chance: +20%"],
        passive="+20 Luck, +15% Qi Recovery, +10% Dao Comprehension, +5% Gu Refinement Success",
        stat_bonuses={
            "cultivation_speed_pct": 0.30, "luck_flat": 20, "breakthrough_chance_pct": 0.20,
            "qi_recovery_pct": 0.15, "dao_comprehension_pct": 0.10,
        },
        names=[
            "Heaven Refining Root", "Limitless Root", "Origin Lotus Root", "Infinite River Root",
            "Primordial Chaos Root", "Boundless Heaven Root", "World Genesis Root",
            "Celestial Origin Root", "Fate River Root", "Dream Sea Root", "Silver Thread Root",
        ],
    ),
    "Divine": Tier(
        name="Divine",
        emoji="🌈",
        display_bonuses=["🌿 Cultivation Speed: +40%", "⭐ Breakthrough Chance: +30%"],
        passive="+25 Luck, +20% Qi Recovery, +15% Dao Comprehension, +10% Gu Refinement Success, +5% Tribulation Success",
        stat_bonuses={
            "cultivation_speed_pct": 0.40, "luck_flat": 25, "breakthrough_chance_pct": 0.30,
            "qi_recovery_pct": 0.20, "dao_comprehension_pct": 0.15,
        },
        names=[
            # NOTE: was "Sovereign Immortal Root" — renamed to "Eternal Heaven Root" to fix a
            # pre-existing data bug: that exact name was ALSO listed as a Unique-tier root
            # just below, which silently broke get_root_spec's name-only lookup for anyone
            # who happened to roll the Divine version (both tiers would resolve to the same
            # spec, incorrectly). No live player had rolled the Divine one at the time of
            # this fix (checked game.db directly) — only the Unique version was in use, so
            # renaming this side is the non-destructive fix.
            "Heaven's Will Root", "Dao Ancestor Root", "Eternal Heaven Root", "Heaven and Earth Root",
            "Great Dao Root", "Origin of Chaos Root", "Primordial Heaven Root", "Supreme Immortal Root",
            "Infinite Dao Root", "Creation Root", "Ancestral Hair Root",
        ],
    ),
    "Unique": Tier(
        name="Unique",
        emoji="💎",
        display_bonuses=[
            "🌿 Cultivation Speed: +60%", "⭐ Breakthrough Chance: +50%", "💧 Qi Recovery: +30%",
            "🍀 Luck: +50", "📚 Dao Comprehension: +25%", "🔨 Gu Refinement Success: +15%",
            "⚡ Tribulation Success: +15%",
        ],
        stat_bonuses={
            "cultivation_speed_pct": 0.60, "luck_flat": 50, "breakthrough_chance_pct": 0.50,
            "qi_recovery_pct": 0.30, "dao_comprehension_pct": 0.25,
        },
        names=[
            "Sovereign Immortal Root", "Star Constellation Inheritor Root", "Giant Sun Inheritor Root",
            "Red Lotus Inheritor Root", "Spectral Soul Inheritor Root", "Limitless Inheritor Root",
            "Reckless Savage Inheritor Root", "Paradise Earth Inheritor Root", "Genesis Lotus Inheritor Root",
            "Primordial Origin Inheritor Root", "Thieving Heaven Inheritor Root",
            "Heaven Refining Inheritor Root", "Fang Yuan's Legacy Root", "Long Hair Ancestor Root",
            "Ancient Solar Spiritual Root", "Ancient Moon Spiritual Root",
            # Deliberately different from the 16 above: no _root_spec entry, no unique_passives
            # line -- still gets this shared tier's own stat_bonuses package (every Unique-tier
            # root does, not just the bespoke ones), but no one-off mechanic of its own. Also
            # exempt from the one-holder-per-name scarcity every OTHER Unique name is bound by
            # (see chargen.GENERIC_UNIQUE_NAMES) -- per explicit request, many people can roll
            # this same one at once, instead of it vanishing from the pool the instant anyone
            # claims it.
            "Nameless Immortal Root",
        ],
        unique_passives={
            "Giant Sun Inheritor Root": "Greatly increases Luck and treasure discovery.",
            "Red Lotus Inheritor Root": "Once per breakthrough, you may retry a failed breakthrough without consuming materials.",
            "Spectral Soul Inheritor Root": "Soul Path techniques deal increased damage and soul cultivation is accelerated.",
            "Star Constellation Inheritor Root": "Faster Dao comprehension and improved deduction abilities.",
            "Thieving Heaven Inheritor Root": "Increased chances to obtain rare resources from events and raids.",
            "Paradise Earth Inheritor Root": "Reduced tribulation difficulty and increased healing.",
            "Limitless Inheritor Root": "Every major breakthrough grants a permanent bonus to a random stat.",
            "Genesis Lotus Inheritor Root": "Significantly increases Wood Path and healing efficiency.",
            "Primordial Origin Inheritor Root": "Superior Qi capacity and essence recovery.",
            "Reckless Savage Inheritor Root": "Massive STR and HP scaling with breakthroughs.",
            "Heaven Refining Inheritor Root": "Near-peerless Gu refinement success and crafting quality.",
            "Sovereign Immortal Root": "Slight bonuses to every cultivation path with no elemental penalties.",
            "Fang Yuan's Legacy Root": "Balanced bonuses across cultivation, luck, refinement, and adaptability, with occasional hidden opportunities during exploration.",
            "Long Hair Ancestor Root": "Vastly superior Blacksmith forging, breaking past the quality ceiling other cultivators are bound by.",
            "Ancient Solar Spiritual Root": "Greatly accelerated cultivation during the day, as the sun's power ascends.",
            "Ancient Moon Spiritual Root": "Greatly accelerated cultivation during the night, as the moon's power ascends.",
        },
    ),
}


# -- Named-root mechanics (Roots/Physiques/Immortal Gu redesign — Phase 1 covered Common/
# Uncommon; Rare/Epic/Legendary followed as later slices of the same migration, per section
# 19's own "Common through Epic roots" phase, done incrementally by tier). Layered on TOP of
# the shared ROOT_TIERS package above — a name in this dict keeps its tier's
# cultivation_speed_pct/breakthrough_chance_pct exactly as before (no double-counting; those
# two keys deliberately never appear below), and gains its own distinct mechanic on top.
# Mythic/Divine/Unique still run on the shared Tier package alone until a later slice gives
# them specs too. Consumers (GameManager, hunt.py, raid.py) all resolve this through
# chargen.get_root_spec(name) — a single lookup, never a scattered `if name == ...`.
#
# The 8 elemental families (Wood/Fire/Water/Earth/Metal/Wind/Moon/Lightning) plus the neutral
# Qi family cover every Common/Uncommon name; Rare adds Strength/Space, Epic adds Soul-Heaven/
# Star-Wisdom, Legendary adds Heaven-cross-system/Human-adaptive — see each section's own
# comment for that tier's new mechanics. Several names are deliberately the same family under
# a different name (e.g. Wood Root/Forest Root), matching the design doc's own "elemental
# roots differentiated by family, not by literal 1:1 unique name" structure. A multi-tag root
# gets its PRIMARY family's full mechanic plus its SECONDARY tag's manual-coherence bonus
# only, at half rate (design doc: "Secondary resonance: X-tag rewards and pages receive half
# the listed thematic benefit") — not the secondary family's whole mechanic set, which would
# double up two full economic bonuses on one root. A handful of source-brief clauses that
# reference systems this codebase doesn't actually have (an auxiliary-manual path-conflict
# penalty, for one) were dropped rather than faked — see the Rare/Legendary section comments
# below for exactly which, and why.
ROOT_SPECS_BY_NAME: Dict[str, "CharacterTraitSpec"] = {}


def _root_spec(name: str, tier: str, tags: tuple, description: str, stat_bonuses: dict = None,
                coherence_tags: dict = None, coherence_categories: dict = None, coherence_flat: int = 0,
                fire_str_bonus_pct: float = 0.0, fire_trigger_fraction: float = 0.0,
                daily_nothing_upgrade: bool = False, skip_path_settling_penalty: bool = False) -> None:
    ROOT_SPECS_BY_NAME[name] = CharacterTraitSpec(
        trait_id=name.lower().replace(" ", "_").replace("'", ""),
        name=name, tier=tier, tags=tags, description=description,
        stat_bonuses=stat_bonuses or {},
        manual_coherence_tags=coherence_tags or {},
        manual_coherence_categories=coherence_categories or {},
        manual_coherence_flat=coherence_flat,
        fire_battle_qi_str_bonus_pct=fire_str_bonus_pct,
        fire_battle_qi_trigger_fraction=fire_trigger_fraction,
        daily_nothing_upgrade=daily_nothing_upgrade,
        skip_path_settling_penalty=skip_path_settling_penalty,
    )


# -- Common (15) -----------------------------------------------------------------------------
_root_spec(
    "Wood Root", "Common", ("wood",),
    "+1% herb/farm yield; healing items restore +2% more; Wood pages preview +2 coherence.",
    {"herb_yield_pct": 0.01, "healing_item_pct": 0.02}, coherence_tags={"wood": 2},
)
_root_spec(
    "Fire Root", "Common", ("fire",),
    "+1% Alchemy/Blacksmith success; Fire/Refinement pages preview +2 coherence; "
    "after spending 30% of your battle Qi in one encounter, +3% STR on your next attack.",
    {"alchemy_success_pct": 0.01, "blacksmith_success_pct": 0.01},
    coherence_tags={"fire": 2, "refinement": 2}, fire_str_bonus_pct=0.03, fire_trigger_fraction=0.30,
)
_root_spec(
    "Water Root", "Common", ("water",),
    "+1% primeval essence restored on use; Water/Circulation pages preview +2 coherence; "
    "/meditate grants +3% more Qi.",
    {"essence_regen_pct": 0.01, "meditate_qi_pct": 0.03},
    coherence_tags={"water": 2}, coherence_categories={"Circulation": 2},
)
_root_spec(
    "Earth Root", "Common", ("earth",),
    "+1% mining yield; Earth/Foundation pages preview +2 coherence; failed breakthroughs "
    "lose 2% less Qi.",
    {"mining_yield_pct": 0.01, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"earth": 2}, coherence_categories={"Foundation": 2},
)
_root_spec(
    "Metal Root", "Common", ("metal",),
    "+1% Blacksmith success; Metal pages preview +2 coherence; dismantling crafted gear "
    "refunds +2% more materials.",
    {"blacksmith_success_pct": 0.01, "gear_dismantle_refund_pct": 0.02}, coherence_tags={"metal": 2},
)
_root_spec(
    "Wind Root", "Common", ("wind",),
    "+1% /explore rarity weighting; Wind/Movement pages preview +2 coherence; flee chance "
    "+2 percentage points.",
    {"explore_luck_bonus_flat": 5, "flee_chance_flat": 0.02}, coherence_tags={"wind": 2, "movement": 2},
)
_root_spec(
    "Moon Root", "Common", ("moon",),
    "+1% clue chance while searching; Moon/Dream/Movement pages preview +2 coherence; "
    "+2% Insight Dust gain.",
    {"clue_chance_bonus_pct": 0.01, "insight_gain_pct": 0.02},
    coherence_tags={"moon": 2, "dream": 2, "movement": 2},
)
_root_spec(
    "Stone Root", "Common", ("earth",),
    "+1% mining yield; Earth/Foundation pages preview +2 coherence; failed breakthroughs "
    "lose 2% less Qi.",
    {"mining_yield_pct": 0.01, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"earth": 2}, coherence_categories={"Foundation": 2},
)
_root_spec(
    "River Root", "Common", ("water",),
    "+1% primeval essence restored on use; Water/Circulation pages preview +2 coherence; "
    "/meditate grants +3% more Qi.",
    {"essence_regen_pct": 0.01, "meditate_qi_pct": 0.03},
    coherence_tags={"water": 2}, coherence_categories={"Circulation": 2},
)
_root_spec(
    "Forest Root", "Common", ("wood",),
    "+1% herb/farm yield; healing items restore +2% more; Wood pages preview +2 coherence.",
    {"herb_yield_pct": 0.01, "healing_item_pct": 0.02}, coherence_tags={"wood": 2},
)
_root_spec(
    "Ash Root", "Common", ("fire",),
    "+1% Alchemy/Blacksmith success; Fire/Refinement pages preview +2 coherence; "
    "after spending 30% of your battle Qi in one encounter, +3% STR on your next attack.",
    {"alchemy_success_pct": 0.01, "blacksmith_success_pct": 0.01},
    coherence_tags={"fire": 2, "refinement": 2}, fire_str_bonus_pct=0.03, fire_trigger_fraction=0.30,
)
_root_spec(
    "Cloud Root", "Common", ("wind",),
    "+1% /explore rarity weighting; Wind/Movement pages preview +2 coherence; flee chance "
    "+2 percentage points.",
    {"explore_luck_bonus_flat": 5, "flee_chance_flat": 0.02}, coherence_tags={"wind": 2, "movement": 2},
)
_root_spec(
    "Mist Root", "Common", ("water",),
    "+1% primeval essence restored on use; Water/Circulation pages preview +2 coherence; "
    "/meditate grants +3% more Qi.",
    {"essence_regen_pct": 0.01, "meditate_qi_pct": 0.03},
    coherence_tags={"water": 2}, coherence_categories={"Circulation": 2},
)
_root_spec(
    "Sand Root", "Common", ("earth",),
    "+1% mining yield; Earth/Foundation pages preview +2 coherence; failed breakthroughs "
    "lose 2% less Qi.",
    {"mining_yield_pct": 0.01, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"earth": 2}, coherence_categories={"Foundation": 2},
)
_root_spec(
    "Lightning Spark Root", "Common", ("lightning",),
    "Empowered Attacks deal +4% damage; Lightning/Breakthrough pages preview +2 coherence; "
    "/meditate restores +2% battle Qi.",
    {"empower_damage_pct": 0.04, "meditate_battle_qi_pct": 0.02},
    coherence_tags={"lightning": 2}, coherence_categories={"Breakthrough": 2},
)

# -- Uncommon (15) ---------------------------------------------------------------------------
_root_spec(
    "Dual Wood-Fire Root", "Uncommon", ("wood", "fire"),
    "+2% herb/farm yield; healing items restore +2% more; Wood pages preview +4 coherence "
    "(Fire pages +1, half resonance).",
    {"herb_yield_pct": 0.02, "healing_item_pct": 0.02}, coherence_tags={"wood": 4, "fire": 1},
)
_root_spec(
    "Dual Water-Earth Root", "Uncommon", ("water", "earth"),
    "+2% primeval essence restored on use; Water/Circulation pages preview +4 coherence "
    "(Earth pages +1, half resonance); /meditate grants +3% more Qi.",
    {"essence_regen_pct": 0.02, "meditate_qi_pct": 0.03},
    coherence_tags={"water": 4, "earth": 1}, coherence_categories={"Circulation": 4},
)
_root_spec(
    "Dual Metal-Wind Root", "Uncommon", ("metal", "wind"),
    "+2% Blacksmith success; Metal pages preview +4 coherence (Wind pages +1, half "
    "resonance); dismantling crafted gear refunds +2% more materials.",
    {"blacksmith_success_pct": 0.02, "gear_dismantle_refund_pct": 0.02}, coherence_tags={"metal": 4, "wind": 1},
)
_root_spec(
    "Storm Root", "Uncommon", ("lightning",),
    "Empowered Attacks deal +4% damage; Lightning/Breakthrough pages preview +4 coherence; "
    "/meditate restores +2% battle Qi.",
    {"empower_damage_pct": 0.04, "meditate_battle_qi_pct": 0.02},
    coherence_tags={"lightning": 4}, coherence_categories={"Breakthrough": 4},
)
_root_spec(
    "Mountain Root", "Uncommon", ("earth",),
    "+2% mining yield; Earth/Foundation pages preview +4 coherence; failed breakthroughs "
    "lose 2% less Qi.",
    {"mining_yield_pct": 0.02, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"earth": 4}, coherence_categories={"Foundation": 4},
)
_root_spec(
    "Jade Root", "Uncommon", ("metal",),
    "+2% Blacksmith success; Metal pages preview +4 coherence; dismantling crafted gear "
    "refunds +2% more materials.",
    {"blacksmith_success_pct": 0.02, "gear_dismantle_refund_pct": 0.02}, coherence_tags={"metal": 4},
)
_root_spec(
    "Deep Sea Root", "Uncommon", ("water",),
    "+2% primeval essence restored on use; Water/Circulation pages preview +4 coherence; "
    "/meditate grants +3% more Qi.",
    {"essence_regen_pct": 0.02, "meditate_qi_pct": 0.03},
    coherence_tags={"water": 4}, coherence_categories={"Circulation": 4},
)
_root_spec(
    "Wild Vine Root", "Uncommon", ("wood",),
    "+2% herb/farm yield; healing items restore +2% more; Wood pages preview +4 coherence.",
    {"herb_yield_pct": 0.02, "healing_item_pct": 0.02}, coherence_tags={"wood": 4},
)
_root_spec(
    "Thunder Root", "Uncommon", ("lightning",),
    "Empowered Attacks deal +4% damage; Lightning/Breakthrough pages preview +4 coherence; "
    "/meditate restores +2% battle Qi.",
    {"empower_damage_pct": 0.04, "meditate_battle_qi_pct": 0.02},
    coherence_tags={"lightning": 4}, coherence_categories={"Breakthrough": 4},
)
_root_spec(
    "Crystal Root", "Uncommon", ("metal",),
    "+2% Blacksmith success; Metal pages preview +4 coherence; dismantling crafted gear "
    "refunds +2% more materials.",
    {"blacksmith_success_pct": 0.02, "gear_dismantle_refund_pct": 0.02}, coherence_tags={"metal": 4},
)
_root_spec(
    "Blooming Lotus Root", "Uncommon", ("wood",),
    "+2% herb/farm yield; healing items restore +2% more; Wood pages preview +4 coherence.",
    {"herb_yield_pct": 0.02, "healing_item_pct": 0.02}, coherence_tags={"wood": 4},
)
_root_spec(
    "Flowing River Root", "Uncommon", ("water",),
    "+2% primeval essence restored on use; Water/Circulation pages preview +4 coherence; "
    "/meditate grants +3% more Qi.",
    {"essence_regen_pct": 0.02, "meditate_qi_pct": 0.03},
    coherence_tags={"water": 4}, coherence_categories={"Circulation": 4},
)
_root_spec(
    "Ironwood Root", "Uncommon", ("wood", "metal"),
    "+2% herb/farm yield; healing items restore +2% more; Wood pages preview +4 coherence "
    "(Metal pages +1, half resonance).",
    {"herb_yield_pct": 0.02, "healing_item_pct": 0.02}, coherence_tags={"wood": 4, "metal": 1},
)
_root_spec(
    "Glacial Root", "Uncommon", ("qi",),
    "+2% /meditate Qi; Qi/Foundation pages preview +4 coherence; +2% primeval essence "
    "restored on use.",
    {"meditate_qi_pct": 0.02, "essence_regen_pct": 0.02},
    coherence_tags={"qi": 4}, coherence_categories={"Foundation": 4},
)
_root_spec(
    "Golden Sand Root", "Uncommon", ("earth", "metal"),
    "+2% mining yield; Earth/Foundation pages preview +4 coherence (Metal pages +1, half "
    "resonance); failed breakthroughs lose 2% less Qi.",
    {"mining_yield_pct": 0.02, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"earth": 4, "metal": 1}, coherence_categories={"Foundation": 4},
)

# -- Rare (15) -------------------------------------------------------------------------------
# Two new families debut here: Strength (Azure Dragon/White Tiger Root — beast_damage_pct is
# the offensive counterpart to Gu's existing beast_damage_reduction_pct, applied in hunt.py/
# raid.py's damage_pct_bonus only against monster_type=="Beast"; beast_material_quantity_bonus_pct
# is a per-hit chance at +1 extra Beast Material, see monsters.roll_loot) and Space (Void Root
# — secret_realm_clue_chance_pct shifts a rolled "clue" toward a secret-realm theme rather
# than inheritance, see GameManager.run_search). Void Root's third clause in the source
# design brief ("reduces auxiliary-manual mismatched-tag compatibility penalty") was dropped:
# no such penalty exists anywhere in this codebase to reduce (auxiliary manuals just apply at
# a flat 35% weight — see database.py's _qi_rate_components), so implementing it honestly
# would mean inventing a whole new penalty system just to then discount it. Left as a two-
# clause mechanic rather than faking the third, same call this session already made once for
# clue_chance_bonus_pct before it existed for real (see rank1_pages.py's own docstring).
_root_spec(
    "Three Element Root", "Rare", ("qi",),
    "+3% /meditate Qi; Qi/Foundation pages preview +6 coherence; +2% primeval essence "
    "restored on use.",
    {"meditate_qi_pct": 0.03, "essence_regen_pct": 0.02},
    coherence_tags={"qi": 6}, coherence_categories={"Foundation": 6},
)
_root_spec(
    "Azure Dragon Root", "Rare", ("strength",),
    "+3% beast damage; Strength/Foundation pages preview +6 coherence; beast materials have "
    "+2% chance at bonus quantity.",
    {"beast_damage_pct": 0.03, "beast_material_quantity_bonus_pct": 0.02},
    coherence_tags={"strength": 6}, coherence_categories={"Foundation": 6},
)
_root_spec(
    "White Tiger Root", "Rare", ("strength",),
    "+3% beast damage; Strength/Foundation pages preview +6 coherence; beast materials have "
    "+2% chance at bonus quantity.",
    {"beast_damage_pct": 0.03, "beast_material_quantity_bonus_pct": 0.02},
    coherence_tags={"strength": 6}, coherence_categories={"Foundation": 6},
)
_root_spec(
    "Vermillion Bird Root", "Rare", ("qi",),
    "+3% /meditate Qi; Qi/Foundation pages preview +6 coherence; +2% primeval essence "
    "restored on use.",
    {"meditate_qi_pct": 0.03, "essence_regen_pct": 0.02},
    coherence_tags={"qi": 6}, coherence_categories={"Foundation": 6},
)
_root_spec(
    "Black Tortoise Root", "Rare", ("qi",),
    "+3% /meditate Qi; Qi/Foundation pages preview +6 coherence; +2% primeval essence "
    "restored on use.",
    {"meditate_qi_pct": 0.03, "essence_regen_pct": 0.02},
    coherence_tags={"qi": 6}, coherence_categories={"Foundation": 6},
)
_root_spec(
    "Starfire Root", "Rare", ("fire", "star"),
    "+3% Alchemy/Blacksmith success; Fire/Refinement pages preview +6 coherence (Star pages "
    "+3, half resonance); after spending 30% of your battle Qi in one encounter, +3% STR on "
    "your next attack.",
    {"alchemy_success_pct": 0.03, "blacksmith_success_pct": 0.03},
    coherence_tags={"fire": 6, "refinement": 6, "star": 3},
    fire_str_bonus_pct=0.03, fire_trigger_fraction=0.30,
)
_root_spec(
    "Void Root", "Rare", ("space",),
    "+3% chance a rolled clue points to a secret realm instead of an inheritance; "
    "Space/Movement pages preview +6 coherence.",
    {"secret_realm_clue_chance_pct": 0.03}, coherence_tags={"space": 6, "movement": 6},
)
_root_spec(
    "Ancient Tree Root", "Rare", ("wood",),
    "+3% herb/farm yield; healing items restore +2% more; Wood pages preview +6 coherence.",
    {"herb_yield_pct": 0.03, "healing_item_pct": 0.02}, coherence_tags={"wood": 6},
)
_root_spec(
    "Ocean Heart Root", "Rare", ("water",),
    "+3% primeval essence restored on use; Water/Circulation pages preview +6 coherence; "
    "/meditate grants +3% more Qi.",
    {"essence_regen_pct": 0.03, "meditate_qi_pct": 0.03},
    coherence_tags={"water": 6}, coherence_categories={"Circulation": 6},
)
_root_spec(
    "Spirit Flame Root", "Rare", ("fire", "soul"),
    "+3% Alchemy/Blacksmith success; Fire/Refinement pages preview +6 coherence (Soul pages "
    "+3, half resonance); after spending 30% of your battle Qi in one encounter, +3% STR on "
    "your next attack.",
    {"alchemy_success_pct": 0.03, "blacksmith_success_pct": 0.03},
    coherence_tags={"fire": 6, "refinement": 6, "soul": 3},
    fire_str_bonus_pct=0.03, fire_trigger_fraction=0.30,
)
_root_spec(
    "Heavenly Thunder Root", "Rare", ("lightning", "heaven"),
    "Empowered Attacks deal +4% damage; Lightning/Breakthrough pages preview +6 coherence "
    "(Heaven pages +3, half resonance); /meditate restores +2% battle Qi.",
    {"empower_damage_pct": 0.04, "meditate_battle_qi_pct": 0.02},
    coherence_tags={"lightning": 6, "heaven": 3}, coherence_categories={"Breakthrough": 6},
)
_root_spec(
    "Emerald Forest Root", "Rare", ("wood",),
    "+3% herb/farm yield; healing items restore +2% more; Wood pages preview +6 coherence.",
    {"herb_yield_pct": 0.03, "healing_item_pct": 0.02}, coherence_tags={"wood": 6},
)
_root_spec(
    "Mountain Vein Root", "Rare", ("earth",),
    "+3% mining yield; Earth/Foundation pages preview +6 coherence; failed breakthroughs "
    "lose 2% less Qi.",
    {"mining_yield_pct": 0.03, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"earth": 6}, coherence_categories={"Foundation": 6},
)
_root_spec(
    "Silver Moon Root", "Rare", ("metal", "moon"),
    "+3% Blacksmith success; Metal pages preview +6 coherence (Moon pages +3, half "
    "resonance); dismantling crafted gear refunds +2% more materials.",
    {"blacksmith_success_pct": 0.03, "gear_dismantle_refund_pct": 0.02},
    coherence_tags={"metal": 6, "moon": 3},
)
_root_spec(
    "Golden Sun Root", "Rare", ("fire", "metal", "sun"),
    "+3% Alchemy/Blacksmith success; Fire/Refinement pages preview +6 coherence (Metal pages "
    "+3, half resonance); after spending 30% of your battle Qi in one encounter, +3% STR on "
    "your next attack.",
    {"alchemy_success_pct": 0.03, "blacksmith_success_pct": 0.03},
    coherence_tags={"fire": 6, "refinement": 6, "metal": 3},
    fire_str_bonus_pct=0.03, fire_trigger_fraction=0.30,
)

# -- Epic (14) -------------------------------------------------------------------------------
# Two more new families: Soul/Heaven (Heavenly Spirit Root — dream_realm_bias_pct is a
# "soul/dream reward weighting" read as "reach dream-realm content more often", the same
# shift-off-"nothing" trick clue_chance_bonus_pct already uses; death_qi_loss_reduction_pct
# softens GameDatabase.apply_death_penalty, floored the same way breakthrough Qi-loss
# reduction is) and Star/Wisdom (Void Star Root — insight_gain_pct is the existing key;
# "once daily, upgrade a nothing search into a minor find" is CharacterTraitSpec's own
# daily_nothing_upgrade flag, backed by GameDatabase.try_use_daily_search_upgrade, the same
# one-per-UTC-day pattern Mythic Physique's fatal-hit negation already uses).
_root_spec(
    "Heavenly Spirit Root", "Epic", ("soul", "heaven"),
    "+4% chance a dud search reaches dream-realm content instead; Soul/Mind pages preview +8 "
    "coherence (Heaven pages +4, half resonance); death Qi loss is reduced by 2%.",
    {"dream_realm_bias_pct": 0.04, "death_qi_loss_reduction_pct": 0.02},
    coherence_tags={"soul": 8, "heaven": 4}, coherence_categories={"Mind": 8},
)
_root_spec(
    "Nine Rivers Root", "Epic", ("water",),
    "+4% primeval essence restored on use; Water/Circulation pages preview +8 coherence; "
    "/meditate grants +4% more Qi.",
    {"essence_regen_pct": 0.04, "meditate_qi_pct": 0.04},
    coherence_tags={"water": 8}, coherence_categories={"Circulation": 8},
)
_root_spec(
    "Ten Thousand Mountain Root", "Epic", ("earth",),
    "+4% mining yield; Earth/Foundation pages preview +8 coherence; failed breakthroughs "
    "lose 2% less Qi.",
    {"mining_yield_pct": 0.04, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"earth": 8}, coherence_categories={"Foundation": 8},
)
_root_spec(
    "Primordial Lightning Root", "Epic", ("lightning",),
    "Empowered Attacks deal +4% damage; Lightning/Breakthrough pages preview +8 coherence; "
    "/meditate restores +2% battle Qi.",
    {"empower_damage_pct": 0.04, "meditate_battle_qi_pct": 0.02},
    coherence_tags={"lightning": 8}, coherence_categories={"Breakthrough": 8},
)
_root_spec(
    "Void Star Root", "Epic", ("star", "space"),
    "+4% Insight Dust gain; Star/Wisdom pages preview +8 coherence (Space pages +4, half "
    "resonance); once daily, a search that would give nothing is upgraded to a minor find.",
    {"insight_gain_pct": 0.04}, coherence_tags={"star": 8, "wisdom": 8, "space": 4},
    daily_nothing_upgrade=True,
)
_root_spec(
    "Nether Flame Root", "Epic", ("fire",),
    "+4% Alchemy/Blacksmith success; Fire/Refinement pages preview +8 coherence; after "
    "spending 30% of your battle Qi in one encounter, +4% STR on your next attack.",
    {"alchemy_success_pct": 0.04, "blacksmith_success_pct": 0.04},
    coherence_tags={"fire": 8, "refinement": 8}, fire_str_bonus_pct=0.04, fire_trigger_fraction=0.30,
)
_root_spec(
    "Ancient Sea Root", "Epic", ("water",),
    "+4% primeval essence restored on use; Water/Circulation pages preview +8 coherence; "
    "/meditate grants +4% more Qi.",
    {"essence_regen_pct": 0.04, "meditate_qi_pct": 0.04},
    coherence_tags={"water": 8}, coherence_categories={"Circulation": 8},
)
_root_spec(
    "World Tree Root", "Epic", ("wood",),
    "+4% herb/farm yield; healing items restore +2% more; Wood pages preview +8 coherence.",
    {"herb_yield_pct": 0.04, "healing_item_pct": 0.02}, coherence_tags={"wood": 8},
)
_root_spec(
    "Celestial Wind Root", "Epic", ("wind", "star"),
    "+4% /explore rarity weighting; Wind/Movement pages preview +8 coherence (Star pages +4, "
    "half resonance); flee chance +2 percentage points.",
    {"explore_luck_bonus_flat": 20, "flee_chance_flat": 0.02},
    coherence_tags={"wind": 8, "movement": 8, "star": 4},
)
_root_spec(
    "Earth Core Root", "Epic", ("earth",),
    "+4% mining yield; Earth/Foundation pages preview +8 coherence; failed breakthroughs "
    "lose 2% less Qi.",
    {"mining_yield_pct": 0.04, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"earth": 8}, coherence_categories={"Foundation": 8},
)
_root_spec(
    "Heaven Vein Root", "Epic", ("earth", "heaven"),
    "+4% mining yield; Earth/Foundation pages preview +8 coherence (Heaven pages +4, half "
    "resonance); failed breakthroughs lose 2% less Qi.",
    {"mining_yield_pct": 0.04, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"earth": 8, "heaven": 4}, coherence_categories={"Foundation": 8},
)
_root_spec(
    "Immortal Spring Root", "Epic", ("wood", "water", "heaven"),
    "+4% herb/farm yield; healing items restore +2% more; Wood pages preview +8 coherence "
    "(Water pages +4, half resonance).",
    {"herb_yield_pct": 0.04, "healing_item_pct": 0.02}, coherence_tags={"wood": 8, "water": 4},
)
_root_spec(
    "Dragon Vein Root", "Epic", ("earth", "strength"),
    "+4% mining yield; Earth/Foundation pages preview +8 coherence (Strength pages +4, half "
    "resonance); failed breakthroughs lose 2% less Qi.",
    {"mining_yield_pct": 0.04, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"earth": 8, "strength": 4}, coherence_categories={"Foundation": 8},
)
_root_spec(
    "Phoenix Vein Root", "Epic", ("fire", "earth"),
    "+4% Alchemy/Blacksmith success; Fire/Refinement pages preview +8 coherence (Earth pages "
    "+4, half resonance); after spending 30% of your battle Qi in one encounter, +4% STR on "
    "your next attack.",
    {"alchemy_success_pct": 0.04, "blacksmith_success_pct": 0.04},
    coherence_tags={"fire": 8, "refinement": 8, "earth": 4}, fire_str_bonus_pct=0.04, fire_trigger_fraction=0.30,
)

# -- Legendary (12) --------------------------------------------------------------------------
# Two more new families: Heaven/cross-system (Heavenly Dao Root, Immortal Sovereign Root —
# insight_gain_pct and breakthrough_qi_loss_reduction_pct are both existing keys reused;
# discovery_quality_bias_pct is new, shifting discovery_gen.roll_difficulty toward Dangerous
# instead of Safe — a harder discovery is also a richer one, per search_data's own reward-by-
# difficulty scaling, which is the closest real lever to the source brief's "+discovery
# quality") and Human/adaptive (Primordial Origin Root — manual_coherence_flat applies to
# every manual regardless of tag match; profession_study_speed_pct shortens whichever
# profession's currently being studied, per GameManager.study). Two clauses were dropped as
# not-implementable rather than faked, same call already made for Void Root: Primordial
# Origin's "path conflicts are reduced slightly" (no such conflict system exists to reduce —
# the doc's own Heaven-tag "half resonance" boilerplate for this entry is skipped too, since
# its own mechanic is already untargeted/universal, so a tag-gated top-up would double-pay
# Heaven pages for no real reason).
_root_spec(
    "Heavenly Dao Root", "Legendary", ("heaven",),
    "+5% Insight Dust gain and a bias toward richer discoveries; Heaven/Rule pages preview "
    "+10 coherence; failed breakthroughs lose 2% less Qi.",
    {"insight_gain_pct": 0.05, "discovery_quality_bias_pct": 0.02, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"heaven": 10, "rule": 10},
)
_root_spec(
    "Earth Mother Root", "Legendary", ("earth",),
    "+5% mining yield; Earth/Foundation pages preview +10 coherence; failed breakthroughs "
    "lose 2% less Qi.",
    {"mining_yield_pct": 0.05, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"earth": 10}, coherence_categories={"Foundation": 10},
)
_root_spec(
    "Primordial Origin Root", "Legendary", ("human", "heaven"),
    "Every manual page previews +5 coherence, regardless of tags; one profession you're "
    "actively studying advances +2% faster.",
    {"profession_study_speed_pct": 0.02}, coherence_flat=5,
)
_root_spec(
    "Chaos Root", "Legendary", ("qi",),
    "+5% /meditate Qi; Qi/Foundation pages preview +10 coherence; +2% primeval essence "
    "restored on use.",
    {"meditate_qi_pct": 0.05, "essence_regen_pct": 0.02},
    coherence_tags={"qi": 10}, coherence_categories={"Foundation": 10},
)
_root_spec(
    "Celestial River Root", "Legendary", ("water", "star"),
    "+5% primeval essence restored on use; Water/Circulation pages preview +10 coherence "
    "(Star pages +5, half resonance); /meditate grants +5% more Qi.",
    {"essence_regen_pct": 0.05, "meditate_qi_pct": 0.05},
    coherence_tags={"water": 10, "star": 5}, coherence_categories={"Circulation": 10},
)
_root_spec(
    "Infinite Sky Root", "Legendary", ("wind", "space"),
    "+5% /explore rarity weighting; Wind/Movement pages preview +10 coherence (Space pages "
    "+5, half resonance); flee chance +2 percentage points.",
    {"explore_luck_bonus_flat": 25, "flee_chance_flat": 0.02},
    coherence_tags={"wind": 10, "movement": 10, "space": 5},
)
_root_spec(
    "Great Wilderness Root", "Legendary", ("qi",),
    "+5% /meditate Qi; Qi/Foundation pages preview +10 coherence; +2% primeval essence "
    "restored on use.",
    {"meditate_qi_pct": 0.05, "essence_regen_pct": 0.02},
    coherence_tags={"qi": 10}, coherence_categories={"Foundation": 10},
)
_root_spec(
    "Genesis Root", "Legendary", ("wood",),
    "+5% herb/farm yield; healing items restore +2% more; Wood pages preview +10 coherence.",
    {"herb_yield_pct": 0.05, "healing_item_pct": 0.02}, coherence_tags={"wood": 10},
)
_root_spec(
    "Heavenly Furnace Root", "Legendary", ("fire", "refinement", "heaven"),
    "+5% Alchemy/Blacksmith success; Fire/Refinement pages preview +10 coherence (Heaven "
    "pages +5, half resonance); after spending 30% of your battle Qi in one encounter, +5% "
    "STR on your next attack.",
    {"alchemy_success_pct": 0.05, "blacksmith_success_pct": 0.05},
    coherence_tags={"fire": 10, "refinement": 10, "heaven": 5}, fire_str_bonus_pct=0.05, fire_trigger_fraction=0.30,
)
_root_spec(
    "Immortal Sovereign Root", "Legendary", ("heaven",),
    "+5% Insight Dust gain and a bias toward richer discoveries; Heaven/Rule pages preview "
    "+10 coherence; failed breakthroughs lose 2% less Qi.",
    {"insight_gain_pct": 0.05, "discovery_quality_bias_pct": 0.02, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"heaven": 10, "rule": 10},
)
_root_spec(
    "Star Sea Root", "Legendary", ("water", "star"),
    "+5% primeval essence restored on use; Water/Circulation pages preview +10 coherence "
    "(Star pages +5, half resonance); /meditate grants +5% more Qi.",
    {"essence_regen_pct": 0.05, "meditate_qi_pct": 0.05},
    coherence_tags={"water": 10, "star": 5}, coherence_categories={"Circulation": 10},
)
_root_spec(
    "Divine Dragon Root", "Legendary", ("wood", "strength"),
    "+5% herb/farm yield; healing items restore +2% more; Wood pages preview +10 coherence "
    "(Strength pages +5, half resonance).",
    {"herb_yield_pct": 0.05, "healing_item_pct": 0.02}, coherence_tags={"wood": 10, "strength": 5},
)

# -- Mythic (11) -----------------------------------------------------------------------------
# One new family: Refinement (Heaven Refining Root — craft_salvage_bonus_pct is new, feeding
# GameManager._alchemy_salvage_bonus_pct, which now covers both craft_pill's existing herb
# salvage AND a brand new equivalent added to craft_gear for this root; the source brief's own
# "Gu Refiner success" clause was dropped — GameManager.upgrade_gu has no success/failure roll
# at all, fusing 2+ duplicates into the next quality always succeeds, so there's no failure
# chance to raise).
_root_spec(
    "Heaven Refining Root", "Mythic", ("refinement", "heaven"),
    "+6% Alchemy/Blacksmith success; Refinement pages preview +12 coherence (Heaven pages +6, "
    "half resonance); failed crafts have a 26% chance to salvage back a material.",
    {"alchemy_success_pct": 0.06, "blacksmith_success_pct": 0.06, "craft_salvage_bonus_pct": 0.26},
    coherence_tags={"refinement": 12, "heaven": 6},
)
_root_spec(
    "Limitless Root", "Mythic", ("qi",),
    "+6% /meditate Qi; Qi/Foundation pages preview +12 coherence; +3% primeval essence "
    "restored on use.",
    {"meditate_qi_pct": 0.06, "essence_regen_pct": 0.03},
    coherence_tags={"qi": 12}, coherence_categories={"Foundation": 12},
)
_root_spec(
    "Origin Lotus Root", "Mythic", ("wood", "heaven"),
    "+6% herb/farm yield; healing items restore +3% more; Wood pages preview +12 coherence "
    "(Heaven pages +6, half resonance).",
    {"herb_yield_pct": 0.06, "healing_item_pct": 0.03}, coherence_tags={"wood": 12, "heaven": 6},
)
_root_spec(
    "Infinite River Root", "Mythic", ("water", "space"),
    "+6% primeval essence restored on use; Water/Circulation pages preview +12 coherence "
    "(Space pages +6, half resonance); /meditate grants +6% more Qi.",
    {"essence_regen_pct": 0.06, "meditate_qi_pct": 0.06},
    coherence_tags={"water": 12, "space": 6}, coherence_categories={"Circulation": 12},
)
_root_spec(
    "Primordial Chaos Root", "Mythic", ("qi",),
    "+6% /meditate Qi; Qi/Foundation pages preview +12 coherence; +3% primeval essence "
    "restored on use.",
    {"meditate_qi_pct": 0.06, "essence_regen_pct": 0.03},
    coherence_tags={"qi": 12}, coherence_categories={"Foundation": 12},
)
_root_spec(
    "Boundless Heaven Root", "Mythic", ("space", "heaven"),
    "+6% chance a rolled clue points to a secret realm instead of an inheritance; "
    "Space/Movement pages preview +12 coherence (Heaven pages +6, half resonance).",
    {"secret_realm_clue_chance_pct": 0.06}, coherence_tags={"space": 12, "movement": 12, "heaven": 6},
)
_root_spec(
    "World Genesis Root", "Mythic", ("wood",),
    "+6% herb/farm yield; healing items restore +3% more; Wood pages preview +12 coherence.",
    {"herb_yield_pct": 0.06, "healing_item_pct": 0.03}, coherence_tags={"wood": 12},
)
_root_spec(
    "Celestial Origin Root", "Mythic", ("star", "heaven"),
    "+6% Insight Dust gain; Star/Wisdom pages preview +12 coherence (Heaven pages +6, half "
    "resonance); once daily, a search that would give nothing is upgraded to a minor find.",
    {"insight_gain_pct": 0.06}, coherence_tags={"star": 12, "wisdom": 12, "heaven": 6},
    daily_nothing_upgrade=True,
)
_root_spec(
    "Fate River Root", "Mythic", ("water", "time", "luck"),
    "+6% primeval essence restored on use; Water/Circulation pages preview +12 coherence "
    "(Time pages +6, half resonance); /meditate grants +6% more Qi.",
    {"essence_regen_pct": 0.06, "meditate_qi_pct": 0.06},
    coherence_tags={"water": 12, "time": 6}, coherence_categories={"Circulation": 12},
)
_root_spec(
    "Dream Sea Root", "Mythic", ("water", "dream"),
    "+6% primeval essence restored on use; Water/Circulation pages preview +12 coherence "
    "(Dream pages +6, half resonance); /meditate grants +6% more Qi.",
    {"essence_regen_pct": 0.06, "meditate_qi_pct": 0.06},
    coherence_tags={"water": 12, "dream": 6}, coherence_categories={"Circulation": 12},
)
# New mechanic: gear_budget_bonus_pct — a Blacksmith-forged piece's total stat-percentage
# budget (see blacksmith.TIER_PCT_BUDGET / roll_gear_stats) is multiplied by (1 +
# gear_budget_bonus_pct) before being split across stats, so a piece rolls stronger than the
# tier's normal ceiling instead of just succeeding more often — separate from (and stacks
# with) blacksmith_success_pct, which only affects whether a craft succeeds at all.
_root_spec(
    "Silver Thread Root", "Mythic", ("metal", "refinement"),
    "Crafted Blacksmith gear rolls an 8% larger stat budget than normal; Refinement pages "
    "preview +12 coherence (Metal pages +6, half resonance).",
    {"gear_budget_bonus_pct": 0.08}, coherence_tags={"refinement": 12, "metal": 6},
)

# -- Divine (11) ------------------------------------------------------------------------------
# One new family: Wisdom/Mind (Dao Ancestor Root). Its third source-brief clause ("manual
# previews reveal one additional flaw or compatibility warning") was dropped rather than
# faked: it references a "hidden line" system that only exists as inert scaffolding in this
# codebase — manual_data.RARITY_HIDDEN_EFFECT_CHANCE is imported but never rolled anywhere,
# and database.py's set_page_hidden_line/discovered_hidden_line column are defined but never
# called by anything. Building a whole new hidden-effect system (what it grants, where it's
# rolled, how it's revealed) just to give one root something to boost is a bigger lift than
# this slice — flagged here for whenever that system gets built for real.
_root_spec(
    "Heaven's Will Root", "Divine", ("heaven",),
    "+8% Insight Dust gain and a bias toward richer discoveries; Heaven/Rule pages preview "
    "+15 coherence; failed breakthroughs lose 2% less Qi.",
    {"insight_gain_pct": 0.08, "discovery_quality_bias_pct": 0.04, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"heaven": 15, "rule": 15},
)
_root_spec(
    "Dao Ancestor Root", "Divine", ("wisdom", "heaven"),
    "+8% Insight Dust gain; Wisdom/Mind pages preview +15 coherence (Heaven pages +8, half "
    "resonance).",
    {"insight_gain_pct": 0.08}, coherence_tags={"wisdom": 15, "heaven": 8}, coherence_categories={"Mind": 15},
)
_root_spec(
    "Eternal Heaven Root", "Divine", ("heaven",),
    "+8% Insight Dust gain and a bias toward richer discoveries; Heaven/Rule pages preview "
    "+15 coherence; failed breakthroughs lose 2% less Qi.",
    {"insight_gain_pct": 0.08, "discovery_quality_bias_pct": 0.04, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"heaven": 15, "rule": 15},
)
_root_spec(
    "Heaven and Earth Root", "Divine", ("earth", "heaven"),
    "+8% mining yield; Earth/Foundation pages preview +15 coherence (Heaven pages +8, half "
    "resonance); failed breakthroughs lose 4% less Qi.",
    {"mining_yield_pct": 0.08, "breakthrough_qi_loss_reduction_pct": 0.04},
    coherence_tags={"earth": 15, "heaven": 8}, coherence_categories={"Foundation": 15},
)
_root_spec(
    "Great Dao Root", "Divine", ("heaven",),
    "+8% Insight Dust gain and a bias toward richer discoveries; Heaven/Rule pages preview "
    "+15 coherence; failed breakthroughs lose 2% less Qi.",
    {"insight_gain_pct": 0.08, "discovery_quality_bias_pct": 0.04, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"heaven": 15, "rule": 15},
)
_root_spec(
    "Origin of Chaos Root", "Divine", ("heaven",),
    "+8% Insight Dust gain and a bias toward richer discoveries; Heaven/Rule pages preview "
    "+15 coherence; failed breakthroughs lose 2% less Qi.",
    {"insight_gain_pct": 0.08, "discovery_quality_bias_pct": 0.04, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"heaven": 15, "rule": 15},
)
_root_spec(
    "Primordial Heaven Root", "Divine", ("heaven",),
    "+8% Insight Dust gain and a bias toward richer discoveries; Heaven/Rule pages preview "
    "+15 coherence; failed breakthroughs lose 2% less Qi.",
    {"insight_gain_pct": 0.08, "discovery_quality_bias_pct": 0.04, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"heaven": 15, "rule": 15},
)
_root_spec(
    "Supreme Immortal Root", "Divine", ("heaven",),
    "+8% Insight Dust gain and a bias toward richer discoveries; Heaven/Rule pages preview "
    "+15 coherence; failed breakthroughs lose 2% less Qi.",
    {"insight_gain_pct": 0.08, "discovery_quality_bias_pct": 0.04, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"heaven": 15, "rule": 15},
)
_root_spec(
    "Infinite Dao Root", "Divine", ("space", "heaven"),
    "+8% chance a rolled clue points to a secret realm instead of an inheritance; "
    "Space/Movement pages preview +15 coherence (Heaven pages +8, half resonance).",
    {"secret_realm_clue_chance_pct": 0.08}, coherence_tags={"space": 15, "movement": 15, "heaven": 8},
)
_root_spec(
    "Creation Root", "Divine", ("heaven",),
    "+8% Insight Dust gain and a bias toward richer discoveries; Heaven/Rule pages preview "
    "+15 coherence; failed breakthroughs lose 2% less Qi.",
    {"insight_gain_pct": 0.08, "discovery_quality_bias_pct": 0.04, "breakthrough_qi_loss_reduction_pct": 0.02},
    coherence_tags={"heaven": 15, "rule": 15},
)
_root_spec(
    "Ancestral Hair Root", "Divine", ("refinement", "heaven"),
    "Crafted Blacksmith gear rolls a 14% larger stat budget than normal; Refinement pages "
    "preview +15 coherence (Heaven pages +8, half resonance).",
    {"gear_budget_bonus_pct": 0.14}, coherence_tags={"refinement": 15, "heaven": 8},
)

# -- Unique (16) ------------------------------------------------------------------------------
# A genuinely different kind of tier from everything above: each root gets its OWN bespoke,
# named rule-changing mechanic (design brief section 8), not a bigger version of one of the 9
# shared elemental families. Every one still uses the same stat_bonuses/coherence machinery
# where its mechanic is naturally numeric, but the mechanic ITSELF — the trigger, the state,
# the guardrail — is implemented as a one-off, localized to whichever single function owns it
# (see each root's own comment below for exactly where). A handful of source-brief clauses
# were simplified or dropped, same "adapt honestly, don't fake it" precedent already used
# repeatedly in the lower tiers — called out per-root below, not silently smoothed over.
# The source brief's other clause, treating all manual path tags as compatible for
# auxiliary-manual eligibility, was dropped: no auxiliary-manual tag-conflict penalty exists
# anywhere in this codebase to become exempt from. Mechanic lives in
# GameManager.change_cultivation_path.
_root_spec(
    "Sovereign Immortal Root", "Unique", ("heaven",),
    "Non-Conflicting Aperture: changing your cultivation path (see the new /change_path) "
    "costs no settling Qi for you, where it costs anyone else 15% of their banked Qi. +3% "
    "Insight Dust; Heaven pages preview +10 coherence.",
    {"insight_gain_pct": 0.03}, coherence_tags={"heaven": 10},
    skip_path_settling_penalty=True,
)
# The source brief's other two clauses — daily danger-label inspection of a pending
# inheritance/dream choice, and pages previewing one refinement level higher — were dropped:
# both need discovery-inspection and page-preview UI this codebase doesn't have yet, not a
# numeric hook this system can adapt.
_root_spec(
    "Star Constellation Inheritor Root", "Unique", ("star", "wisdom"),
    "Star Deduction: +25% Insight Dust gain; Star/Wisdom pages preview +15 coherence.",
    {"insight_gain_pct": 0.25}, coherence_tags={"star": 15, "wisdom": 15},
)
# Mechanic lives in GameManager.run_search's Luck Tide reroll and raid.py's _on_victory.
_root_spec(
    "Giant Sun Inheritor Root", "Unique", ("fire", "sun", "strength", "luck"),
    "Luck Tide: once daily, your first /search minor_find or encounter reward is rolled "
    "twice and keeps the better result; +3% /explore rarity weighting and +3% chance a clue "
    "points to a secret realm; raiding alongside 2+ others grants a small Connect Luck bonus "
    "to spirit-stone rewards.",
    {"explore_luck_bonus_flat": 15, "secret_realm_clue_chance_pct": 0.03},
    coherence_tags={"fire": 10, "star": 5},
)
# Mechanic lives in GameManager.attempt_breakthrough.
_root_spec(
    "Red Lotus Inheritor Root", "Unique", ("wood", "time"),
    "Red Lotus Reversal: once every 7 days, a failed breakthrough refunds 70% of its Qi cost "
    "and grants one immediate retry at -10 percentage points success chance — the retry's "
    "own result is final, win or lose, and can't itself trigger a second reversal. +2% "
    "herb/farm yield; Wood/Time pages preview +10 coherence.",
    {"herb_yield_pct": 0.02}, coherence_tags={"wood": 10, "time": 5},
)
# Mechanic lives in raid.py's _on_victory / GameManager's unique weekly-resource payout.
_root_spec(
    "Spectral Soul Inheritor Root", "Unique", ("soul",),
    "Soul Devouring: raid boss victories generate Soul Fragments (capped weekly), "
    "immediately converted into bonus Insight Dust — never from defeating another player. "
    "Soul pages preview +10 coherence.",
    {}, coherence_tags={"soul": 10},
)
# Mechanic lives in GameManager.attempt_breakthrough's great_realm_crossing branch.
_root_spec(
    "Limitless Inheritor Root", "Unique", ("qi",),
    "Boundless Foundation: every Great Realm crossing (up to 5 times total) permanently "
    "grants +1% to a rotating foundation-stat family. +3% /meditate Qi; Qi/Foundation pages "
    "preview +10 coherence.",
    {"meditate_qi_pct": 0.03}, coherence_tags={"qi": 10}, coherence_categories={"Foundation": 10},
)
# Simplified from the source brief's 3-way switchable Totem (Beast/Strength/Transformation)
# with a cooldown-gated swap: that needs a dedicated selection command this slice didn't
# build; Beast was picked as the one most other systems here already support.
_root_spec(
    "Reckless Savage Inheritor Root", "Unique", ("qi",),
    "Totem of Myriad Forms: permanently bonded to the Beast Totem — +6% beast damage.",
    {"beast_damage_pct": 0.06}, coherence_tags={"qi": 10},
)
# Mechanic lives in raid.py's _on_victory / GameManager's unique weekly-resource payout.
_root_spec(
    "Paradise Earth Inheritor Root", "Unique", ("earth",),
    "Merciful Earth: death Qi loss reduced by 4%, failed breakthroughs lose 4% less Qi; "
    "surviving a raid victory without dealing the most damage grants a Merit (capped "
    "weekly), immediately spent on bonus healing — Merit is never earned from trades or "
    "arranged PvP, only real raid participation.",
    {"death_qi_loss_reduction_pct": 0.04, "breakthrough_qi_loss_reduction_pct": 0.04},
    coherence_tags={"earth": 10},
)
# Mechanic lives in craft_pill/craft_gear/run_search's SPECIAL_RESULTS branch / GameManager's
# unique weekly-resource payout.
_root_spec(
    "Genesis Lotus Inheritor Root", "Unique", ("wood",),
    "Karmic Divine Tree: successful crafts and completed discoveries grow Karma (capped "
    "weekly), immediately spent on bonus Qi. +4% herb/farm yield; healing items restore +3% "
    "more.",
    {"herb_yield_pct": 0.04, "healing_item_pct": 0.03}, coherence_tags={"wood": 10},
)
# Mechanic lives in GameManager.cultivate.
_root_spec(
    "Primordial Origin Inheritor Root", "Unique", ("human", "heaven"),
    "Qi Sea Origin: once daily, /cultivate converts 10% of your current primeval essence "
    "into a temporary cultivation-speed buff — the essence spent is gone either way, buff or "
    "not. +3% primeval essence restored on use.",
    {"essence_regen_pct": 0.03}, coherence_tags={"heaven": 10},
)
# Mechanic lives in raid.py's _on_victory.
_root_spec(
    "Thieving Heaven Inheritor Root", "Unique", ("heaven",),
    "Otherworldly Theft: once daily, defeating a raid boss grants one extra roll from a "
    "restricted tiered-material pool that never includes Gu, canon, or Unique-catalog items. "
    "+3% chance a clue points to a secret realm.",
    {"secret_realm_clue_chance_pct": 0.03}, coherence_tags={"heaven": 10},
)
# The source brief's weekly one-band quality promotion was dropped: crafted gear rolls a
# continuous stat budget, not a discrete quality band the way Gu quality tiers work, so
# there's no clean "promote by one band" to hook.
_root_spec(
    "Heaven Refining Inheritor Root", "Unique", ("refinement", "heaven"),
    "Refine All Things: +8% Alchemy/Blacksmith success; a 35% chance to salvage a material "
    "back from any craft attempt; Refinement pages preview +10 coherence.",
    {"alchemy_success_pct": 0.08, "blacksmith_success_pct": 0.08, "craft_salvage_bonus_pct": 0.35},
    coherence_tags={"refinement": 10, "heaven": 5},
)
# Simplified from the source brief's daily switch between four schemes (Cultivation/Combat/
# Refinement/Exploration) plus Perseverance stacks from difficult actions: that needs a
# dedicated daily-choice command and a new stack-tracking system this slice didn't build;
# Cultivation was picked as the scheme every character benefits from regardless of playstyle.
_root_spec(
    "Fang Yuan's Legacy Root", "Unique", ("qi",),
    "Benefits Above All: permanently committed to the Cultivation scheme — +4% primeval "
    "essence restored on use, +4% /meditate Qi.",
    {"essence_regen_pct": 0.04, "meditate_qi_pct": 0.04}, coherence_tags={"qi": 10},
)
_root_spec(
    "Long Hair Ancestor Root", "Unique", ("refinement", "heaven"),
    "Ancestral Forging: crafted Blacksmith gear rolls a 25% larger stat budget than normal, "
    "breaking past the ceiling a normal forge is bound by; +5% Blacksmith success. "
    "Refinement pages preview +10 coherence.",
    {"gear_budget_bonus_pct": 0.25, "blacksmith_success_pct": 0.05}, coherence_tags={"refinement": 10},
)
# No stat_bonuses of their own -- the day/night cultivation-speed swing is a flat +15% that
# only applies for half the day, which doesn't fit the always-on additive stat_bonuses pool
# any other root spec here uses. Mechanic lives directly in GameDatabase._qi_rate_components
# (localized root_name check, same "Unique mechanics check name directly" precedent as Giant
# Sun Inheritor Root's Luck Tide / Sovereign Immortal Root's path-settling skip).
_root_spec(
    "Ancient Solar Spiritual Root", "Unique", ("fire", "sun"),
    "Solar Ascendance: +15% cultivation speed during the 12 hours of daytime (06:00-18:00 UTC) "
    "-- doubled to +30% if your Dao Companion holds the Ancient Moon Spiritual Root.",
    {}, coherence_tags={"fire": 10, "sun": 10},
)
_root_spec(
    "Ancient Moon Spiritual Root", "Unique", ("moon",),
    "Lunar Ascendance: +15% cultivation speed during the 12 hours of night (18:00-06:00 UTC) "
    "-- doubled to +30% if your Dao Companion holds the Ancient Solar Spiritual Root.",
    {}, coherence_tags={"moon": 20},
)


# Genuinely separate objects from ROOT_TIER_ORDER/ROOT_TIER_WEIGHTS (not aliases) so a
# physique-only tier -- Godly, below -- can exist without leaking into the root ladder
# (ROOT_TIERS has no "Godly" entry; roll_root would KeyError if it ever rolled one). Every
# call site that used to treat these as interchangeable with the root versions (manager.py's
# reroll-batch helpers, shop.py's _best_roll, premium_view.py's tier select/histogram) now
# takes the correct list explicitly instead of assuming they're the same object.
PHYSIQUE_TIER_ORDER = list(ROOT_TIER_ORDER) + ["Godly"]
PHYSIQUE_TIER_WEIGHTS = dict(ROOT_TIER_WEIGHTS)
# ~1-in-100,000: the rest of the table already sums to 10000, so a weight of 0.1 lands at
# 0.1 / 10000.1 ~= 1/100001 -- deliberately far rarer than Unique's own 10/10000 (1/1000).
PHYSIQUE_TIER_WEIGHTS["Godly"] = 0.1

PHYSIQUE_TIERS: Dict[str, Tier] = {
    "Common": Tier(
        name="Common",
        emoji="⚪",
        display_bonuses=["+5% Main Stat", "+2% HP", "+2% DEF"],
        stat_bonuses={"str_pct": 0.05, "hp_pct": 0.02, "def_pct": 0.02},
        names=[
            "Iron Skin Body", "Swift Foot Body", "Strong Bone Body", "Healthy Spirit Body",
            "Sturdy Frame Body", "Stone Muscle Body", "Clear Mind Body", "Forest Walker Body",
            "River Walker Body", "Wild Hunter Body", "Bronze Flesh Body", "Firm Tendon Body",
            "Balanced Physique", "Enduring Body", "Steel Blood Body",
        ],
    ),
    "Uncommon": Tier(
        name="Uncommon",
        emoji="🟢",
        display_bonuses=["+10% Main Stat", "+5% HP", "+5% DEF", "+5% Breakthrough Stat Growth"],
        stat_bonuses={"str_pct": 0.10, "hp_pct": 0.05, "def_pct": 0.05},
        names=[
            "Spring Tendon Body", "Steel Bone Body", "Golden Blood Body", "Flowing Muscle Body",
            "Mountain Back Body", "Moonlight Body", "Forest Heart Body", "Stone Heart Body",
            "Iron Vein Body", "Swift Wind Body", "Deep Breath Body", "Thunder Muscle Body",
            "Lotus Body", "Azure Beast Body",
        ],
    ),
    "Rare": Tier(
        name="Rare",
        emoji="🔵",
        display_bonuses=["+18% Main Stat", "+10% HP", "+10% DEF", "+10% Stat Growth", "+5 Luck"],
        passive="Small damage reduction.",
        stat_bonuses={"str_pct": 0.18, "hp_pct": 0.10, "def_pct": 0.10, "luck_flat": 5},
        names=[
            "Dragon Scale Body", "Phoenix Feather Body", "Tiger Bone Body", "Black Tortoise Body",
            "Star Body", "Void Body", "Ancient Beast Body", "Spirit Vessel Body",
            "Heavenly Muscle Body", "Earth Spirit Body", "Ocean Soul Body", "Thunder Lord Body",
            "Golden Giant Body", "Immortal Blood Body",
        ],
    ),
    "Epic": Tier(
        name="Epic",
        emoji="🟣",
        display_bonuses=["+28% Main Stat", "+15% HP", "+15% DEF", "+15% Stat Growth", "+10 Luck"],
        passive="Gain a temporary stat boost after every breakthrough.",
        stat_bonuses={"str_pct": 0.28, "hp_pct": 0.15, "def_pct": 0.15, "luck_flat": 10},
        names=[
            "Heavenly Battle Body", "Primordial Giant Body", "Celestial Dragon Body", "World Tree Body",
            "Endless Ocean Body", "Divine Thunder Body", "Phoenix Rebirth Body", "Starborn Body",
            "Void Walker Body", "Mountain King Body", "Immortal Vessel Body", "Sky Sovereign Body",
            "Ancient Titan Body",
        ],
    ),
    "Legendary": Tier(
        name="Legendary",
        emoji="🟠",
        display_bonuses=["+40% Main Stat", "+20% HP", "+20% DEF", "+20% Stat Growth", "+15 Luck"],
        passive="Every breakthrough permanently increases a random stat.",
        stat_bonuses={"str_pct": 0.40, "hp_pct": 0.20, "def_pct": 0.20, "luck_flat": 15},
        names=[
            "Heaven Defying Body", "Primordial Chaos Body", "Dao Vessel Body", "Celestial Emperor Body",
            "Immortal Saint Body", "Heavenly Giant Body", "Boundless Battle Body", "Genesis Body",
            "World Creation Body", "Limitless Physique",
        ],
    ),
    "Mythic": Tier(
        name="Mythic",
        emoji="🔴",
        display_bonuses=["+55% Main Stat", "+30% HP", "+25% DEF", "+30% Stat Growth", "+20 Luck"],
        passive="Ignore the first fatal hit each day. Permanent Qi Recovery +15%.",
        stat_bonuses={"str_pct": 0.55, "hp_pct": 0.30, "def_pct": 0.25, "luck_flat": 20, "qi_recovery_pct": 0.15},
        names=[
            "Chaos Immortal Body", "Primordial Dao Body", "Infinite Battle Body", "Eternal Dragon Body",
            "Celestial Sovereign Body", "Heavenly Origin Body", "Void Sovereign Body",
            "Immortal Emperor Body", "Supreme Saint Body", "Star Emperor Body",
        ],
    ),
    "Divine": Tier(
        name="Divine",
        emoji="🌈",
        display_bonuses=["+75% Main Stat", "+40% HP", "+35% DEF", "+40% Stat Growth", "+30 Luck"],
        passive="+10% Cultivation Speed, +10% Breakthrough Chance, +20% Qi Recovery, +10% Tribulation Success",
        stat_bonuses={
            "str_pct": 0.75, "hp_pct": 0.40, "def_pct": 0.35, "luck_flat": 30,
            "cultivation_speed_pct": 0.10, "breakthrough_chance_pct": 0.10, "qi_recovery_pct": 0.20,
        },
        names=[
            "Supreme Dao Physique", "Sovereign Heaven Body", "Heaven and Earth Physique",
            "Primordial Origin Body", "Infinite Immortal Body", "Perfect Dao Vessel",
            "Supreme Chaos Body", "Creation Body", "Great Dao Physique",
        ],
    ),
    "Unique": Tier(
        name="Unique",
        emoji="💎",
        display_bonuses=[
            "+100% Main Stat", "+50% HP", "+50% DEF", "+50% Stat Growth", "+50 Luck",
            "+15% Cultivation Speed", "+15% Breakthrough Chance", "+20% Qi Recovery",
            "+20% Dao Comprehension", "+15% Tribulation Success",
        ],
        stat_bonuses={
            "str_pct": 1.00, "hp_pct": 0.50, "def_pct": 0.50, "luck_flat": 50, "cultivation_speed_pct": 0.15,
            "breakthrough_chance_pct": 0.15, "qi_recovery_pct": 0.20, "dao_comprehension_pct": 0.20,
        },
        names=[
            "True Human Physique", "Great Strength True Martial Physique", "Northern Dark Ice Soul Physique",
            "Boundless Forest Samsara Physique", "Blazing Glory Lightning Brilliance Physique",
            "Myriad Gold Wondrous Essence Physique", "Carefree Wisdom Heart Physique",
            "Desolate Ancient Moon Physique", "Universe Great Derivation Physique",
            "Verdant Great Sun Physique", "Dream Reality Seeker Physique", "Sovereign Immortal Fetus Physique",
            "Heavenly Solar Physique", "Heavenly Lunar Physique", "Twin Gu Sovereign Physique",
            "Blazing Glory Sunfire Physique", "Blood Sea Demon Physique", "Immovable Mountain Physique",
            # Same carve-out as the root ladder's own "Nameless Immortal Root" -- no
            # _physique_spec entry, no unique_passives line, no one-off mechanic; still gets
            # this shared tier's own big stat_bonuses package, and is exempt from the
            # one-holder-per-name scarcity (see chargen.GENERIC_UNIQUE_NAMES) so many people
            # can roll this exact one at once.
            "Nameless Immortal Physique",
        ],
        unique_passives={
            "True Human Physique": "+20% Cultivation Speed and no penalties when changing cultivation paths.",
            "Great Strength True Martial Physique": "STR gains from breakthroughs are doubled and physical attacks deal bonus damage.",
            "Northern Dark Ice Soul Physique": "Greatly enhances Ice Path and Soul Path techniques while increasing Qi regeneration.",
            "Boundless Forest Samsara Physique": "Exceptional healing and Wood Path affinity; regeneration continues during combat.",
            "Blazing Glory Lightning Brilliance Physique": "Massive SPD growth and bonus Lightning Path damage with a chance to act twice.",
            "Myriad Gold Wondrous Essence Physique": "Increased Qi capacity, Gu refinement success, and Metal Path effectiveness.",
            "Carefree Wisdom Heart Physique": "Accelerated Dao comprehension, higher Luck, and enhanced deduction abilities.",
            "Desolate Ancient Moon Physique": "Strong affinity for Moon, Dream, and Illusion Paths with increased breakthrough success at night.",
            "Universe Great Derivation Physique": "Faster attainment growth across all paths and reduced tribulation penalties.",
            "Verdant Great Sun Physique": "Superior cultivation speed, abundant Qi recovery, and powerful Fire/Wood synergy.",
            "Dream Reality Seeker Physique": "Greatly improves Dream Path cultivation and can occasionally glimpse future opportunities during exploration.",
            "Sovereign Immortal Fetus Physique": "Can cultivate any Dao Path without conflict, gains balanced growth in all stats, and suffers no affinity penalties.",
            "Heavenly Solar Physique": "Each attack this encounter stacks a growing damage bonus, up to +20% at full stacks.",
            "Heavenly Lunar Physique": "Each attack this encounter further weakens the target's defense against you, up to +25% armor penetration at full stacks.",
            "Twin Gu Sovereign Physique": "Can bind and equip a second Gu — its passive stat bonuses apply, but only the first Gu's combat ability and any named special effects (Fixed Immortal Travel, Worldly Escape, Battle Intent, etc.) remain active.",
            "Blazing Glory Sunfire Physique": "Every landed attack sears the target with a burn totaling 5% of their max HP over the next few rounds.",
            "Blood Sea Demon Physique": "Heals 12% of damage dealt on every landed attack; below 50% HP, gains +18% STR.",
            "Immovable Mountain Physique": "+30% DEF, +15% HP; surviving a landed hit reflects 30% of the damage taken straight back at the attacker.",
        },
    ),
    "Godly": Tier(
        name="Godly",
        emoji="👑",
        # Identical package to Unique above (same stat_bonuses, just copied rather than
        # shared, so either tier's numbers can be tuned independently later) plus its own
        # extra passive -- deliberately not a bigger Main Stat/HP/DEF package, since the
        # request was "same stats as Unique" with the growth passive as the sole upgrade.
        display_bonuses=[
            "+100% Main Stat", "+50% HP", "+50% DEF", "+50% Stat Growth", "+50 Luck",
            "+15% Cultivation Speed", "+15% Breakthrough Chance", "+20% Qi Recovery",
            "+20% Dao Comprehension", "+15% Tribulation Success", "+2% Random Stat per Breakthrough",
        ],
        passive="Every breakthrough permanently grows a random stat by 2% of its current value (see GameManager.attempt_breakthrough).",
        stat_bonuses={
            "str_pct": 1.00, "hp_pct": 0.50, "def_pct": 0.50, "luck_flat": 50, "cultivation_speed_pct": 0.15,
            "breakthrough_chance_pct": 0.15, "qi_recovery_pct": 0.20, "dao_comprehension_pct": 0.20,
        },
        names=["Godly Physique"],
    ),
}


# -- Named-physique mechanics (Roots/Physiques/Immortal Gu redesign — physiques' own slice of
# the migration, started after the full root ladder). Same "layer on top of the shared tier
# package, never touch it" contract roots use — physique_tier's own str_pct/hp_pct/def_pct
# keep applying to literally everyone in that tier exactly as before (see
# chargen.compute_final_stats' physique_spec parameter), and a named physique only ever ADDS
# its own thematic stat/mechanic on top, never replaces the shared one. This is a deliberately
# safer reading of the design brief's own "Swift Foot Body should favor SPD rather than the
# same STR package as Iron Skin Body" complaint than literally swapping the tier's stat out
# would be — it keeps every non-yet-covered tier's existing bonus completely intact with zero
# risk of silently zeroing something out for players whose physique tier hasn't gotten a named
# slice yet, at the cost of a SPD-focused physique also still carrying a little STR from the
# shared package. Reuses CharacterTraitSpec as-is (no new dataclass fields needed — see each
# family's own stat_bonuses key below); PHYSIQUE_SPECS_BY_NAME is looked up via
# chargen.get_physique_spec(name), the exact same pattern as roots.
#
# Only Common (15 names, 9 families) is covered so far — the same "start with one tier, extend
# later" incremental approach the root ladder used across many separate slices.
PHYSIQUE_SPECS_BY_NAME: Dict[str, "CharacterTraitSpec"] = {}


def _physique_spec(name: str, tier: str, tags: tuple, description: str, stat_bonuses: dict = None) -> None:
    PHYSIQUE_SPECS_BY_NAME[name] = CharacterTraitSpec(
        trait_id=name.lower().replace(" ", "_").replace("'", ""),
        name=name, tier=tier, tags=tags, description=description,
        stat_bonuses=stat_bonuses or {},
    )


# -- Common (15) -----------------------------------------------------------------------------
# New stat_bonuses keys this tier introduces (all consumed in hunt.py/raid.py — see each
# hook's own comment for exactly where): guard_stack_def_pct (Iron Skin family — each Guard
# action this encounter adds a stack, capped at 2), dodge_momentum_str_bonus_pct (Swift Foot
# family — first successful dodge each encounter arms a bonus on the next attack, same
# pending-flag shape as a root's own Fire-family trigger), every_third_attack_bonus_pct
# (Strong Bone family), battle_qi_regen_bonus_pct + first_gu_use_discount_flat (Sturdy Frame
# family), high_hp_damage_reduction_pct (Stone Muscle family — only while above 60% HP, same
# threshold shape as Rockman race's own damage reduction), encounter_start_adaptive_stat_pct
# (Clear Mind family — auto-applied to whichever of ATK/DEF/SPD the player is proportionally
# weakest in against this specific enemy, since there's no pre-encounter choice UI), and
# post_hunt_heal_pct (Forest Walker family) / guard_or_potion_qi_restore_pct (River Walker
# family). Everything else reuses a root system key already wired up (death_qi_loss_reduction_pct,
# dream_realm_bias_pct, beast_damage_pct, mining_yield_pct, healing_item_pct, meditate_qi_pct,
# flee_chance_flat) — folded into the SAME lookup path a root's own bonus already goes through
# (see manager.py's renamed _trait_bonus / compute_equipment_bonuses' fold-in).
#
# Two source-brief clauses were dropped rather than faked, same precedent as the root ladder:
# Healthy Spirit family's "first control effect each encounter has resist chance" (no
# player-facing stun/silence/control-effect system exists anywhere in this codebase to resist
# — Frostbinder's Freeze is the only CC-like effect, and it's only ever applied TO enemies,
# never to a player) and Clear Mind family's "manual flaws are easier to reveal" (manual
# preview already shows a page's full flaw_pool unconditionally — see manual_view.py — so
# there's nothing currently hidden to make "easier to reveal").
_physique_spec(
    "Iron Skin Body", "Common", ("metal",),
    "Each Guard this encounter adds a stack of +3% incoming-damage reduction, up to 2 stacks.",
    {"guard_stack_def_pct": 0.03},
)
_physique_spec(
    "Swift Foot Body", "Common", ("wind",),
    "First successful dodge each encounter grants Momentum: +3% STR on your next attack; "
    "flee chance +1 percentage point.",
    {"dodge_momentum_str_bonus_pct": 0.03, "flee_chance_flat": 0.01},
)
_physique_spec(
    "Strong Bone Body", "Common", ("strength",),
    "Every third successful basic Attack deals +6% damage; +1% beast damage.",
    {"every_third_attack_bonus_pct": 0.06, "beast_damage_pct": 0.01},
)
_physique_spec(
    "Healthy Spirit Body", "Common", ("soul",),
    "Death Qi loss reduced by 2%; +2% chance a dud search reaches dream-realm content instead.",
    {"death_qi_loss_reduction_pct": 0.02, "dream_realm_bias_pct": 0.02},
)
_physique_spec(
    "Sturdy Frame Body", "Common", ("qi",),
    "+2% battle-Qi regeneration; your first Gu activation each encounter costs 1 less Qi.",
    {"battle_qi_regen_bonus_pct": 0.02, "first_gu_use_discount_flat": 1},
)
_physique_spec(
    "Stone Muscle Body", "Common", ("earth", "strength"),
    "While above 60% HP, take 3% less damage; +2% mining yield.",
    {"high_hp_damage_reduction_pct": 0.03, "mining_yield_pct": 0.02},
)
_physique_spec(
    "Clear Mind Body", "Common", ("wisdom",),
    "At the start of each encounter, automatically gain +3% to whichever of ATK/DEF/SPD "
    "you're proportionally weakest in against that opponent.",
    {"encounter_start_adaptive_stat_pct": 0.03},
)
_physique_spec(
    "Forest Walker Body", "Common", ("wood",),
    "Healing items restore +2% more; after winning a hunt, recover 3% max HP.",
    {"healing_item_pct": 0.02, "post_hunt_heal_pct": 0.03},
)
_physique_spec(
    "River Walker Body", "Common", ("water",),
    "Using Guard or a potion restores 3% of max battle Qi, once per encounter; /meditate "
    "grants +2% more Qi.",
    {"guard_or_potion_qi_restore_pct": 0.03, "meditate_qi_pct": 0.02},
)
_physique_spec(
    "Wild Hunter Body", "Common", ("qi",),
    "+2% battle-Qi regeneration; your first Gu activation each encounter costs 1 less Qi.",
    {"battle_qi_regen_bonus_pct": 0.02, "first_gu_use_discount_flat": 1},
)
_physique_spec(
    "Bronze Flesh Body", "Common", ("metal",),
    "Each Guard this encounter adds a stack of +3% incoming-damage reduction, up to 2 stacks.",
    {"guard_stack_def_pct": 0.03},
)
_physique_spec(
    "Firm Tendon Body", "Common", ("qi",),
    "+2% battle-Qi regeneration; your first Gu activation each encounter costs 1 less Qi.",
    {"battle_qi_regen_bonus_pct": 0.02, "first_gu_use_discount_flat": 1},
)
_physique_spec(
    "Balanced Physique", "Common", ("qi",),
    "+2% battle-Qi regeneration; your first Gu activation each encounter costs 1 less Qi.",
    {"battle_qi_regen_bonus_pct": 0.02, "first_gu_use_discount_flat": 1},
)
_physique_spec(
    "Enduring Body", "Common", ("qi",),
    "+2% battle-Qi regeneration; your first Gu activation each encounter costs 1 less Qi.",
    {"battle_qi_regen_bonus_pct": 0.02, "first_gu_use_discount_flat": 1},
)
_physique_spec(
    "Steel Blood Body", "Common", ("metal",),
    "Each Guard this encounter adds a stack of +3% incoming-damage reduction, up to 2 stacks.",
    {"guard_stack_def_pct": 0.03},
)

# -- Uncommon (14) ---------------------------------------------------------------------------
# Two new families debut here: Moonlight (Moonlight Body — reuses the pre-existing
# dodge_chance_pct/dream_realm_bias_pct keys plus a new gu_miss_qi_refund_pct: the first Gu
# ability that MISSES each encounter refunds half its Qi cost, see hunt.py/raid.py's
# identical handling) and Thunder Muscle (empower_damage_pct — reused — plus a new
# first_empower_discount_flat, the Empower equivalent of Sturdy Frame's first-Gu-use discount).
_physique_spec(
    "Spring Tendon Body", "Uncommon", ("wood", "water"),
    "Healing items restore +4% more; after winning a hunt, recover 4% max HP.",
    {"healing_item_pct": 0.04, "post_hunt_heal_pct": 0.04},
)
_physique_spec(
    "Steel Bone Body", "Uncommon", ("metal", "strength"),
    "Each Guard this encounter adds a stack of +4% incoming-damage reduction, up to 2 stacks.",
    {"guard_stack_def_pct": 0.04},
)
_physique_spec(
    "Golden Blood Body", "Uncommon", ("metal",),
    "Each Guard this encounter adds a stack of +4% incoming-damage reduction, up to 2 stacks.",
    {"guard_stack_def_pct": 0.04},
)
_physique_spec(
    "Flowing Muscle Body", "Uncommon", ("strength",),
    "Every third successful basic Attack deals +8% damage; +2% beast damage.",
    {"every_third_attack_bonus_pct": 0.08, "beast_damage_pct": 0.02},
)
_physique_spec(
    "Mountain Back Body", "Uncommon", ("earth",),
    "While above 60% HP, take 4% less damage; +4% mining yield.",
    {"high_hp_damage_reduction_pct": 0.04, "mining_yield_pct": 0.04},
)
_physique_spec(
    "Moonlight Body", "Uncommon", ("moon",),
    "+3% dodge chance; +4% chance a dud search reaches dream-realm content instead; the "
    "first Gu ability that misses each encounter refunds 50% of its Qi cost.",
    {"dodge_chance_pct": 0.03, "dream_realm_bias_pct": 0.04, "gu_miss_qi_refund_pct": 0.50},
)
_physique_spec(
    "Forest Heart Body", "Uncommon", ("wood",),
    "Healing items restore +4% more; after winning a hunt, recover 4% max HP.",
    {"healing_item_pct": 0.04, "post_hunt_heal_pct": 0.04},
)
_physique_spec(
    "Stone Heart Body", "Uncommon", ("earth",),
    "While above 60% HP, take 4% less damage; +4% mining yield.",
    {"high_hp_damage_reduction_pct": 0.04, "mining_yield_pct": 0.04},
)
_physique_spec(
    "Iron Vein Body", "Uncommon", ("earth", "metal"),
    "While above 60% HP, take 4% less damage; +4% mining yield.",
    {"high_hp_damage_reduction_pct": 0.04, "mining_yield_pct": 0.04},
)
_physique_spec(
    "Swift Wind Body", "Uncommon", ("wind",),
    "First successful dodge each encounter grants Momentum: +4% STR on your next attack; "
    "flee chance +2 percentage points.",
    {"dodge_momentum_str_bonus_pct": 0.04, "flee_chance_flat": 0.02},
)
_physique_spec(
    "Deep Breath Body", "Uncommon", ("qi",),
    "+4% battle-Qi regeneration; your first Gu activation each encounter costs 2 less Qi.",
    {"battle_qi_regen_bonus_pct": 0.04, "first_gu_use_discount_flat": 2},
)
_physique_spec(
    "Thunder Muscle Body", "Uncommon", ("lightning", "strength"),
    "Empowered Attacks deal +8% damage; your first Empower each encounter costs 2 less "
    "battle Qi.",
    {"empower_damage_pct": 0.08, "first_empower_discount_flat": 2},
)
_physique_spec(
    "Lotus Body", "Uncommon", ("wood",),
    "Healing items restore +4% more; after winning a hunt, recover 4% max HP.",
    {"healing_item_pct": 0.04, "post_hunt_heal_pct": 0.04},
)
_physique_spec(
    "Azure Beast Body", "Uncommon", ("strength",),
    "Every third successful basic Attack deals +8% damage; +2% beast damage.",
    {"every_third_attack_bonus_pct": 0.08, "beast_damage_pct": 0.02},
)

# -- Rare (14) --------------------------------------------------------------------------------
# Three new families: Star (encounter_start_adaptive_stat_pct — reuses Clear Mind's own
# mechanism/key rather than a near-duplicate "lowest of my own raw stats" variant, see the
# Common section's own note on this — plus insight_gain_pct, reused), Void (a new
# flee_reroll_once flag plus the reused secret_realm_clue_chance_pct), and Phoenix Feather
# (a new low_hp_str_pct_bonus — the % version of the existing flat low_hp_atk_bonus Gu passive
# — plus a new kill_qi_restore_pct, battle Qi back on defeating an enemy).
_physique_spec(
    "Dragon Scale Body", "Rare", ("strength",),
    "Every third successful basic Attack deals +10% damage; +3% beast damage.",
    {"every_third_attack_bonus_pct": 0.10, "beast_damage_pct": 0.03},
)
_physique_spec(
    "Phoenix Feather Body", "Rare", ("fire",),
    "Below 50% HP, gain +9% STR; defeating an enemy restores 4% max battle Qi.",
    {"low_hp_str_pct_bonus": 0.09, "kill_qi_restore_pct": 0.04},
)
_physique_spec(
    "Tiger Bone Body", "Rare", ("strength",),
    "Every third successful basic Attack deals +10% damage; +3% beast damage.",
    {"every_third_attack_bonus_pct": 0.10, "beast_damage_pct": 0.03},
)
_physique_spec(
    "Black Tortoise Body", "Rare", ("qi",),
    "+6% battle-Qi regeneration; your first Gu activation each encounter costs 3 less Qi.",
    {"battle_qi_regen_bonus_pct": 0.06, "first_gu_use_discount_flat": 3},
)
_physique_spec(
    "Star Body", "Rare", ("star",),
    "At the start of each encounter, automatically gain +6% to whichever of ATK/DEF/SPD "
    "you're proportionally weakest in; +6% Insight Dust gain from studying pages.",
    {"encounter_start_adaptive_stat_pct": 0.06, "insight_gain_pct": 0.06},
)
_physique_spec(
    "Void Body", "Rare", ("space",),
    "Once per encounter, a failed flee gets one immediate reroll; +6% chance a clue points "
    "to a secret realm instead of an inheritance.",
    {"flee_reroll_once": 1.0, "secret_realm_clue_chance_pct": 0.06},
)
_physique_spec(
    "Ancient Beast Body", "Rare", ("strength",),
    "Every third successful basic Attack deals +10% damage; +3% beast damage.",
    {"every_third_attack_bonus_pct": 0.10, "beast_damage_pct": 0.03},
)
_physique_spec(
    "Spirit Vessel Body", "Rare", ("soul",),
    "Death Qi loss reduced by 4%; +4% chance a dud search reaches dream-realm content instead.",
    {"death_qi_loss_reduction_pct": 0.04, "dream_realm_bias_pct": 0.04},
)
_physique_spec(
    "Heavenly Muscle Body", "Rare", ("strength", "heaven"),
    "Every third successful basic Attack deals +10% damage; +3% beast damage.",
    {"every_third_attack_bonus_pct": 0.10, "beast_damage_pct": 0.03},
)
_physique_spec(
    "Earth Spirit Body", "Rare", ("earth", "soul"),
    "While above 60% HP, take 5% less damage; +6% mining yield.",
    {"high_hp_damage_reduction_pct": 0.05, "mining_yield_pct": 0.06},
)
_physique_spec(
    "Ocean Soul Body", "Rare", ("water", "soul"),
    "Using Guard or a potion restores 5% of max battle Qi, once per encounter; /meditate "
    "grants +6% more Qi.",
    {"guard_or_potion_qi_restore_pct": 0.05, "meditate_qi_pct": 0.06},
)
_physique_spec(
    "Thunder Lord Body", "Rare", ("lightning",),
    "Empowered Attacks deal +10% damage; your first Empower each encounter costs 3 less "
    "battle Qi.",
    {"empower_damage_pct": 0.10, "first_empower_discount_flat": 3},
)
_physique_spec(
    "Golden Giant Body", "Rare", ("metal", "strength"),
    "Each Guard this encounter adds a stack of +5% incoming-damage reduction, up to 2 stacks.",
    {"guard_stack_def_pct": 0.05},
)
_physique_spec(
    "Immortal Blood Body", "Rare", ("heaven",),
    "Great Realm breakthroughs grant a 6% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.06},
)

# -- Epic (13) --------------------------------------------------------------------------------
_physique_spec(
    "Heavenly Battle Body", "Epic", ("strength", "heaven"),
    "Every third successful basic Attack deals +12% damage; +4% beast damage.",
    {"every_third_attack_bonus_pct": 0.12, "beast_damage_pct": 0.04},
)
_physique_spec(
    "Primordial Giant Body", "Epic", ("strength",),
    "Every third successful basic Attack deals +12% damage; +4% beast damage.",
    {"every_third_attack_bonus_pct": 0.12, "beast_damage_pct": 0.04},
)
_physique_spec(
    "Celestial Dragon Body", "Epic", ("star", "strength"),
    "At the start of each encounter, automatically gain +7% to whichever of ATK/DEF/SPD "
    "you're proportionally weakest in; +8% Insight Dust gain from studying pages.",
    {"encounter_start_adaptive_stat_pct": 0.07, "insight_gain_pct": 0.08},
)
_physique_spec(
    "World Tree Body", "Epic", ("wood",),
    "Healing items restore +8% more; after winning a hunt, recover 6% max HP.",
    {"healing_item_pct": 0.08, "post_hunt_heal_pct": 0.06},
)
_physique_spec(
    "Endless Ocean Body", "Epic", ("water",),
    "Using Guard or a potion restores 6% of max battle Qi, once per encounter; /meditate "
    "grants +8% more Qi.",
    {"guard_or_potion_qi_restore_pct": 0.06, "meditate_qi_pct": 0.08},
)
_physique_spec(
    "Divine Thunder Body", "Epic", ("wood", "lightning"),
    "Healing items restore +8% more; after winning a hunt, recover 6% max HP.",
    {"healing_item_pct": 0.08, "post_hunt_heal_pct": 0.06},
)
_physique_spec(
    "Phoenix Rebirth Body", "Epic", ("fire",),
    "Below 50% HP, gain +11% STR; defeating an enemy restores 5% max battle Qi.",
    {"low_hp_str_pct_bonus": 0.11, "kill_qi_restore_pct": 0.05},
)
_physique_spec(
    "Starborn Body", "Epic", ("star",),
    "At the start of each encounter, automatically gain +7% to whichever of ATK/DEF/SPD "
    "you're proportionally weakest in; +8% Insight Dust gain from studying pages.",
    {"encounter_start_adaptive_stat_pct": 0.07, "insight_gain_pct": 0.08},
)
_physique_spec(
    "Void Walker Body", "Epic", ("space",),
    "Once per encounter, a failed flee gets one immediate reroll; +8% chance a clue points "
    "to a secret realm instead of an inheritance.",
    {"flee_reroll_once": 1.0, "secret_realm_clue_chance_pct": 0.08},
)
_physique_spec(
    "Mountain King Body", "Epic", ("earth",),
    "While above 60% HP, take 6% less damage; +8% mining yield.",
    {"high_hp_damage_reduction_pct": 0.06, "mining_yield_pct": 0.08},
)
_physique_spec(
    "Immortal Vessel Body", "Epic", ("heaven",),
    "Great Realm breakthroughs grant an 8% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.08},
)
_physique_spec(
    "Sky Sovereign Body", "Epic", ("wind",),
    "First successful dodge each encounter grants Momentum: +6% STR on your next attack; "
    "flee chance +4 percentage points.",
    {"dodge_momentum_str_bonus_pct": 0.06, "flee_chance_flat": 0.04},
)
_physique_spec(
    "Ancient Titan Body", "Epic", ("strength",),
    "Every third successful basic Attack deals +12% damage; +4% beast damage.",
    {"every_third_attack_bonus_pct": 0.12, "beast_damage_pct": 0.04},
)

# -- Legendary (10) --------------------------------------------------------------------------
_physique_spec(
    "Heaven Defying Body", "Legendary", ("heaven",),
    "Great Realm breakthroughs grant a 10% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.10},
)
_physique_spec(
    "Primordial Chaos Body", "Legendary", ("qi",),
    "+10% battle-Qi regeneration; your first Gu activation each encounter costs 5 less Qi.",
    {"battle_qi_regen_bonus_pct": 0.10, "first_gu_use_discount_flat": 5},
)
_physique_spec(
    "Dao Vessel Body", "Legendary", ("heaven",),
    "Great Realm breakthroughs grant a 10% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.10},
)
_physique_spec(
    "Celestial Emperor Body", "Legendary", ("star",),
    "At the start of each encounter, automatically gain +8% to whichever of ATK/DEF/SPD "
    "you're proportionally weakest in; +10% Insight Dust gain from studying pages.",
    {"encounter_start_adaptive_stat_pct": 0.08, "insight_gain_pct": 0.10},
)
_physique_spec(
    "Immortal Saint Body", "Legendary", ("heaven",),
    "Great Realm breakthroughs grant a 10% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.10},
)
_physique_spec(
    "Heavenly Giant Body", "Legendary", ("strength", "heaven"),
    "Every third successful basic Attack deals +14% damage; +5% beast damage.",
    {"every_third_attack_bonus_pct": 0.14, "beast_damage_pct": 0.05},
)
_physique_spec(
    "Boundless Battle Body", "Legendary", ("space", "strength"),
    "Once per encounter, a failed flee gets one immediate reroll; +10% chance a clue points "
    "to a secret realm instead of an inheritance.",
    {"flee_reroll_once": 1.0, "secret_realm_clue_chance_pct": 0.10},
)
_physique_spec(
    "Genesis Body", "Legendary", ("wood",),
    "Healing items restore +10% more; after winning a hunt, recover 7% max HP.",
    {"healing_item_pct": 0.10, "post_hunt_heal_pct": 0.07},
)
_physique_spec(
    "World Creation Body", "Legendary", ("heaven",),
    "Great Realm breakthroughs grant a 10% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.10},
)
_physique_spec(
    "Limitless Physique", "Legendary", ("qi",),
    "+10% battle-Qi regeneration; your first Gu activation each encounter costs 5 less Qi.",
    {"battle_qi_regen_bonus_pct": 0.10, "first_gu_use_discount_flat": 5},
)

# -- Mythic (10) ------------------------------------------------------------------------------
_physique_spec(
    "Chaos Immortal Body", "Mythic", ("heaven",),
    "Great Realm breakthroughs grant a 12% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.12},
)
_physique_spec(
    "Primordial Dao Body", "Mythic", ("heaven",),
    "Great Realm breakthroughs grant a 12% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.12},
)
_physique_spec(
    "Infinite Battle Body", "Mythic", ("space", "strength"),
    "Once per encounter, a failed flee gets one immediate reroll; +12% chance a clue points "
    "to a secret realm instead of an inheritance.",
    {"flee_reroll_once": 1.0, "secret_realm_clue_chance_pct": 0.12},
)
_physique_spec(
    "Eternal Dragon Body", "Mythic", ("strength",),
    "Every third successful basic Attack deals +16% damage; +6% beast damage.",
    {"every_third_attack_bonus_pct": 0.16, "beast_damage_pct": 0.06},
)
_physique_spec(
    "Celestial Sovereign Body", "Mythic", ("star",),
    "At the start of each encounter, automatically gain +9% to whichever of ATK/DEF/SPD "
    "you're proportionally weakest in; +12% Insight Dust gain from studying pages.",
    {"encounter_start_adaptive_stat_pct": 0.09, "insight_gain_pct": 0.12},
)
_physique_spec(
    "Heavenly Origin Body", "Mythic", ("heaven",),
    "Great Realm breakthroughs grant a 12% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.12},
)
_physique_spec(
    "Void Sovereign Body", "Mythic", ("space",),
    "Once per encounter, a failed flee gets one immediate reroll; +12% chance a clue points "
    "to a secret realm instead of an inheritance.",
    {"flee_reroll_once": 1.0, "secret_realm_clue_chance_pct": 0.12},
)
_physique_spec(
    "Immortal Emperor Body", "Mythic", ("heaven",),
    "Great Realm breakthroughs grant a 12% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.12},
)
_physique_spec(
    "Supreme Saint Body", "Mythic", ("heaven",),
    "Great Realm breakthroughs grant a 12% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.12},
)
_physique_spec(
    "Star Emperor Body", "Mythic", ("star",),
    "At the start of each encounter, automatically gain +9% to whichever of ATK/DEF/SPD "
    "you're proportionally weakest in; +12% Insight Dust gain from studying pages.",
    {"encounter_start_adaptive_stat_pct": 0.09, "insight_gain_pct": 0.12},
)

# -- Divine (9) -------------------------------------------------------------------------------
# One new family: Primordial Origin Body's own Great Realm mechanic — "permanently add +1 to
# two different random foundation stats" every crossing (see GameManager.attempt_breakthrough,
# right after Limitless Inheritor Root's Boundless Foundation block) — no stat_bonuses key of
# its own; the mechanic is a direct name check, same documented exception CharacterTraitSpec's
# own docstring already carves out for Unique-tier mechanics, used here a tier early since
# this one genuinely doesn't fit the shared-family shape. Its "manual path conflicts reduced
# slightly" clause was dropped, same reasoning as the root ladder's own Void/Primordial Origin
# Root: no such conflict system exists anywhere in this codebase to reduce.
_physique_spec(
    "Supreme Dao Physique", "Divine", ("heaven",),
    "Great Realm breakthroughs grant a 14% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.14},
)
_physique_spec(
    "Sovereign Heaven Body", "Divine", ("heaven",),
    "Great Realm breakthroughs grant a 14% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.14},
)
_physique_spec(
    "Heaven and Earth Physique", "Divine", ("earth", "heaven"),
    "While above 60% HP, take 9% less damage; +8% mining yield.",
    {"high_hp_damage_reduction_pct": 0.09, "mining_yield_pct": 0.08},
)
_physique_spec(
    "Primordial Origin Body", "Divine", ("human", "heaven"),
    "Every Great Realm crossing permanently adds +1 to two different random foundation "
    "stats.",
    {},
)
_physique_spec(
    "Infinite Immortal Body", "Divine", ("space", "heaven"),
    "Once per encounter, a failed flee gets one immediate reroll; +14% chance a clue points "
    "to a secret realm instead of an inheritance.",
    {"flee_reroll_once": 1.0, "secret_realm_clue_chance_pct": 0.14},
)
_physique_spec(
    "Perfect Dao Vessel", "Divine", ("heaven",),
    "Great Realm breakthroughs grant a 14% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.14},
)
_physique_spec(
    "Supreme Chaos Body", "Divine", ("heaven",),
    "Great Realm breakthroughs grant a 14% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.14},
)
_physique_spec(
    "Creation Body", "Divine", ("heaven",),
    "Great Realm breakthroughs grant a 14% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.14},
)
_physique_spec(
    "Great Dao Physique", "Divine", ("heaven",),
    "Great Realm breakthroughs grant a 14% stronger temporary Vigor buff.",
    {"great_realm_vigor_buff_pct": 0.14},
)

# -- Unique (14) ------------------------------------------------------------------------------
# Unlike the Unique ROOT ladder (15 fully bespoke, purpose-built mechanics), every Unique
# PHYSIQUE below reuses mechanics already wired up by the tiers above it, at strong Unique-
# tier magnitudes, rather than building 12 more one-off systems in the same slice. This is a
# deliberate, documented scope simplification — each entry's own comment names the source
# brief's real mechanic and why a flat reused-key version stands in for it. All twelve still
# get a real, working, tested effect; none are flavor-text-only. (The final two, Heavenly
# Solar/Lunar Physique, are the one exception — genuinely new one-off mechanics, see their own
# comment below.)
# Simplified from the source brief's per-Great-Realm choice of up to 3 active Adaptations:
# this is a flat always-on version of a few of them rather than a selectable loadout, which
# would need a dedicated choice command.
_physique_spec(
    "True Human Physique", "Unique", ("human",),
    "Human Potential: a broad, adaptable spread — +5% herb/farm yield, +8% battle-Qi "
    "regeneration, +5% Alchemy success.",
    {"herb_yield_pct": 0.05, "battle_qi_regen_bonus_pct": 0.08, "alchemy_success_pct": 0.05},
)
# Simplified from the source brief's Martial Intent system (stacks up to 5 on successful
# Attacks, consumed for a finishing blow, lost on a Guard or miss): this is a flat always-on
# version of the same power level instead of a stack-and-release mechanic.
_physique_spec(
    "Great Strength True Martial Physique", "Unique", ("strength",),
    "+15% physical damage.",
    {"physical_damage_pct": 0.15},
)
# Simplified from the source brief's Frozen Soul system (stacks build from taking damage
# rather than Guarding, and cap at 5 with a freeze effect at max stacks): reuses the Iron
# Skin family's own Guard-stack mechanism instead of a new damage-taken trigger.
_physique_spec(
    "Northern Dark Ice Soul Physique", "Unique", ("moon", "soul"),
    "Each Guard this encounter adds a stack of +9% incoming-damage reduction, up to 2 "
    "stacks; +5% dodge chance.",
    {"guard_stack_def_pct": 0.09, "dodge_chance_pct": 0.05},
)
# Simplified from the source brief's per-round regrowth (small heal every round, not just on
# victory) plus a Samsara Seed carried into your NEXT encounter: this is a bigger one-time
# version at the same moment Forest Walker's own post-hunt heal already fires.
_physique_spec(
    "Boundless Forest Samsara Physique", "Unique", ("wood", "space"),
    "Healing items restore +10% more; after winning a hunt, recover 15% max HP.",
    {"healing_item_pct": 0.10, "post_hunt_heal_pct": 0.15},
)
# Simplified from the source brief's Brilliance-charge system (3 Empowers charge a bonus
# extra attack at reduced power, then an Exhausted penalty): a flat always-on Empower bonus
# instead of the charge-and-release/Exhaustion cycle.
_physique_spec(
    "Blazing Glory Lightning Brilliance Physique", "Unique", ("fire", "lightning"),
    "Empowered Attacks deal +15% damage; your first Empower each encounter costs 6 less "
    "battle Qi.",
    {"empower_damage_pct": 0.15, "first_empower_discount_flat": 6},
)
_physique_spec(
    "Myriad Gold Wondrous Essence Physique", "Unique", ("metal", "refinement"),
    "+10% Alchemy/Blacksmith success; a 40% chance to salvage a material back from any "
    "craft attempt.",
    {"alchemy_success_pct": 0.10, "blacksmith_success_pct": 0.10, "craft_salvage_bonus_pct": 0.40},
)
# Simplified from the source brief's own version, which reacts once AFTER the enemy's first
# action rather than at encounter start, and also reveals exact manual coherence contributors
# in the assembly preview — no such reactive-timing hook or contributor breakdown exists yet.
_physique_spec(
    "Carefree Wisdom Heart Physique", "Unique", ("wisdom",),
    "At the start of each encounter, automatically gain +10% to whichever of ATK/DEF/SPD "
    "you're proportionally weakest in; +10% Insight Dust gain from studying pages.",
    {"encounter_start_adaptive_stat_pct": 0.10, "insight_gain_pct": 0.10},
)
# Simplified from the source brief's 4-phase cycle (New/Waxing/Full/Waning, each favoring a
# different system, advancing after meaningful actions): a flat always-on blend of two of the
# phases' own effects instead of a rotating exclusive cycle.
_physique_spec(
    "Desolate Ancient Moon Physique", "Unique", ("moon",),
    "+8% dodge chance; +8% chance a dud search reaches dream-realm content instead.",
    {"dodge_chance_pct": 0.08, "dream_realm_bias_pct": 0.08},
)
# Simplified from the source brief's Derivation Entries system (victories against different
# monster archetypes earn equippable counters like beast defense or assassin evasion): reuses
# the Void family's own mechanism instead of a new per-archetype counter catalog.
_physique_spec(
    "Universe Great Derivation Physique", "Unique", ("space", "wisdom"),
    "Once per encounter, a failed flee gets one immediate reroll; +14% chance a clue points "
    "to a secret realm instead of an inheritance.",
    {"flee_reroll_once": 1.0, "secret_realm_clue_chance_pct": 0.14},
)
# Simplified from the source brief's dual-threshold system (a cultivation/healing mode above
# 70% HP, a Fire/Wood combat mode below 40% HP, switching live): a flat always-on blend of
# both thresholds' flavor instead of a live mode switch.
_physique_spec(
    "Verdant Great Sun Physique", "Unique", ("wood", "fire", "sun"),
    "+8% herb/farm yield; while above 60% HP, take 9% less damage.",
    {"herb_yield_pct": 0.08, "high_hp_damage_reduction_pct": 0.09},
)
# Simplified from the source brief's dream-boon preservation (turn one temporary dream-realm
# buff into a real 24-hour one) and partial-success-on-failure system: no dream-realm
# buff-preservation or partial-success hook exists yet to extend.
_physique_spec(
    "Dream Reality Seeker Physique", "Unique", ("dream",),
    "+14% chance a dud search reaches dream-realm content instead; +8% Insight Dust gain "
    "from studying pages.",
    {"dream_realm_bias_pct": 0.14, "insight_gain_pct": 0.08},
)
# The source brief's own mechanic — ignore the first path-conflict penalty on equipped
# Gu/manuals/accessories, plus two swappable loadout presets — was dropped: no path-conflict
# penalty or loadout-preset system exists anywhere in this codebase, same reasoning as the
# root ladder's own Sovereign Immortal Root.
_physique_spec(
    "Sovereign Immortal Fetus Physique", "Unique", ("human", "heaven"),
    "+8% Insight Dust gain; Great Realm breakthroughs grant a 14% stronger temporary Vigor "
    "buff.",
    {"insight_gain_pct": 0.08, "great_realm_vigor_buff_pct": 0.14},
)
# Two genuinely new one-off mechanics (no existing family fits a growing, capped per-attack
# stack of bonus damage/armor penetration) rather than a lower-tier family reused at a bigger
# magnitude, same allowance the ROOT ladder already uses freely (e.g. Long Hair Ancestor
# Root's gear_budget_bonus_pct). Both keys are consumed by a new per-encounter stack counter
# in hunt.py/raid.py, mirroring the Iron Skin family's own _guard_stacks shape, feeding
# combat.resolve_attack's existing damage_pct_bonus/armor_penetration_pct parameters.
_physique_spec(
    "Heavenly Solar Physique", "Unique", ("fire", "sun", "strength"),
    "Solar Flare: each successful basic Attack this encounter stacks a growing damage bonus, "
    "+4% per stack, up to +20% at 5 stacks. Radiant Ward: in a raid, every OTHER ally fighting "
    "alongside you gains +12% DEF for as long as you're both still standing.",
    {"solar_stack_damage_pct": 0.04, "ally_def_aura_pct": 0.12},
)
_physique_spec(
    "Twin Gu Sovereign Physique", "Unique", ("qi", "human"),
    "A vessel steady enough to bind a second Gu at once (see /equipment's Gu category) -- "
    "+10% HP, +10% DEF, +8% Insight Dust gain.",
    {"hp_pct": 0.10, "def_pct": 0.10, "insight_gain_pct": 0.08},
)
_physique_spec(
    "Heavenly Lunar Physique", "Unique", ("moon",),
    "Lunar Sunder: each successful basic Attack this encounter further weakens the target's "
    "defense against you, +5% armor penetration per stack, up to +25% at 5 stacks. Moonlit "
    "Cleave: in a raid, your basic Attacks strike every enemy still standing instead of just "
    "one.",
    {"lunar_stack_armor_pen_pct": 0.05, "lunar_aoe_attacks": 1},
)
# Three more genuinely new one-off Unique mechanics, same allowance as Heavenly Solar/Lunar
# just above. sunfire_burn_max_hp_pct and retaliation_damage_pct are each consumed by a new
# bit of state in hunt.py/raid.py (mirroring the Fire Dao Path burn / Iron Skin guard-stack
# shapes already there); lifesteal_percent and low_hp_str_pct_bonus need no new plumbing at
# all -- both already ride the existing generic bonus pool (see manager.SPECIAL_BONUS_KEYS
# and hunt.py/raid.py's own _player_combat_stats, same key Phoenix Feather Body already uses).
_physique_spec(
    "Blazing Glory Sunfire Physique", "Unique", ("fire", "sun"),
    "Sunfire Brand: every landed attack this encounter sears the target with a burn totaling "
    "5% of their max HP, dealt over the next few rounds -- refreshes (doesn't stack) on each "
    "new landed hit.",
    {"sunfire_burn_max_hp_pct": 0.05},
)
_physique_spec(
    "Blood Sea Demon Physique", "Unique", ("blood", "strength"),
    "Blood Sea Hunger: heals 12% of damage dealt back to you on every landed attack; below "
    "50% HP, gain +18% STR as the hunger takes over.",
    {"lifesteal_percent": 0.12, "low_hp_str_pct_bonus": 0.18},
)
_physique_spec(
    "Immovable Mountain Physique", "Unique", ("earth", "strength"),
    "Mountain's Resolve: +30% DEF, +15% HP; surviving a landed hit reflects 30% of the "
    "damage taken straight back at the attacker.",
    {"def_pct": 0.30, "hp_pct": 0.15, "retaliation_damage_pct": 0.30},
)

# Godly tier's sole physique -- its whole mechanic (permanently grow a random stat by 2% of
# its current value on every breakthrough) is a direct name check in
# GameManager.attempt_breakthrough, not a stat_bonuses key, same carve-out Primordial Origin
# Body already gets (see content/validation.py's BESPOKE_MECHANIC_PHYSIQUE_NAMES) -- so this
# spec exists purely to satisfy "every physique needs a description" and carries no
# stat_bonuses of its own; the shared Godly Tier package above already matches Unique's.
_physique_spec(
    "Godly Physique", "Godly", ("heaven",),
    "Every breakthrough permanently grows a random stat by 2% of its current value, on top "
    "of the same package Unique-tier physiques carry.",
    {},
)


PATHS: Dict[str, Path] = {
    "Righteous": Path(
        name="Righteous",
        tagline="Order, honor, and the strength of alliances.",
        display_bonuses=[
            "Cultivation Speed: +10%", "Breakthrough Chance: +10%", "Luck: +5",
            "Sect Contribution Gain: +20%", "Reputation Gain: +25%", "Shop Prices: -10%",
        ],
        passive_name="Heavenly Blessing",
        passive_text="Every successful breakthrough grants a small amount of bonus cultivation. Higher reputation unlocks exclusive sect techniques.",
        weakness="PvP penalties for attacking innocents. More difficult to obtain forbidden Gu and Demonic inheritances.",
        # "Bonus cultivation on breakthrough" reuses the same dao_comprehension_pct mechanic
        # Inkman's race passive already uses — a chance at a bonus qi refund on success.
        stat_bonuses={"cultivation_speed_pct": 0.10, "luck_flat": 5, "breakthrough_chance_pct": 0.10, "dao_comprehension_pct": 0.05},
    ),
    "Demonic": Path(
        name="Demonic",
        tagline="Power above all else.",
        display_bonuses=["Cultivation Speed: +20%", "Breakthrough Chance: +5%", "STR: +10%", "Qi: +10%", "Luck: -10"],
        passive_name="Blood Refinement",
        passive_text=(
            "Killing bosses or players grants Blood Essence. Blood Essence can be spent for: "
            "temporary cultivation boosts, faster Gu refinement, faster healing, higher damage."
        ),
        weakness="Lower reputation. More NPC enemies. Harder tribulations (+10% difficulty).",
        stat_bonuses={"cultivation_speed_pct": 0.20, "str_pct": 0.10, "qi_pct": 0.10, "luck_flat": -10, "breakthrough_chance_pct": 0.05},
    ),
    "Rogue": Path(
        name="Rogue",
        tagline="No sect. No master. Only freedom.",
        display_bonuses=["Cultivation Speed: +8%", "Breakthrough Chance: +12%", "Luck: +15", "Speed: +10%"],
        passive_name="Wandering Fortune",
        passive_text="Higher chance to encounter hidden inheritances, secret realms, rare merchants, lucky events, and ancient ruins.",
        weakness="No sect bonuses. No sect protection. Must obtain resources independently.",
        stat_bonuses={"cultivation_speed_pct": 0.08, "spd_pct": 0.10, "luck_flat": 15, "breakthrough_chance_pct": 0.12},
    ),
}
