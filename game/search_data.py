"""
Static data for /search and the discoveries it can produce — economy constants, region/focus
modifiers, universal + source-specific loot tables, room/event tables, and the named
inheritance/secret-realm/dream-realm theme templates (design doc sections 3, 4, 9, 10, 14).

Regions reuse this game's existing 7 Great Realms (see realms.py) rather than inventing a
parallel region list — a player's own realm and any Great Realm at or below it are the
regions they can search, matching the doc's "current region plus previously unlocked lower
regions" rule with zero new lore to maintain.
"""

from . import realms

# -- Search economy (section 3) --------------------------------------------------------------
SEARCH_DAILY_CHARGES = 3
SEARCH_MAX_CHARGES = 9
SEARCH_RECHARGE_SECONDS = 10 * 60  # TESTING: 10 min recharge (normally 8 * 3600, ~3/day) — revert once testing is done

SEARCH_FOCUS_OPTIONS = ["Balanced", "Manuals", "Gu", "Equipment", "Materials", "Clues"]

# Discovery expiry once found but not yet entered.
DISCOVERY_EXPIRY_SECONDS = {
    "inheritance": 48 * 3600, "secret_realm": 36 * 3600, "dream_realm": 24 * 3600,
    "battlefield": 24 * 3600, "region_dream_realm": 24 * 3600,
}

REGIONS = [great["name"] for great in realms.GREAT_REALMS]  # index == rank - 1


def region_rank(region: str) -> int:
    return REGIONS.index(region) + 1 if region in REGIONS else 1


def available_regions(great_realm_index: int) -> list:
    """Current region plus every previously-unlocked lower region."""
    return REGIONS[: great_realm_index + 1]


# -- Base search result weights (section 3) ---------------------------------------------------
BASE_SEARCH_WEIGHTS = {
    "nothing": 25.0, "minor_find": 25.0, "encounter": 18.0, "clue": 16.0,
    "inheritance": 7.0, "secret_realm": 6.0, "dream_realm": 3.0,
}
SPECIAL_RESULTS = {"inheritance", "secret_realm", "dream_realm"}

# Focus shifts weight toward its matching category without ever hitting 0% elsewhere —
# expressed as relative weight MULTIPLIERS applied before renormalizing.
SEARCH_FOCUS_MODIFIERS = {
    "Balanced": {},
    "Manuals": {"dream_realm": 1.6, "inheritance": 1.3, "clue": 1.2},
    "Gu": {"secret_realm": 1.4, "encounter": 1.3},
    "Equipment": {"inheritance": 1.3, "encounter": 1.2},
    "Materials": {"minor_find": 1.4, "secret_realm": 1.2},
    "Clues": {"clue": 1.6},
}

# -- Momentum / pity (section 3) ---------------------------------------------------------------
MOMENTUM_CLUE_THRESHOLD = 8
MOMENTUM_SPECIAL_THRESHOLD = 15
CLUE_FRAGMENTS_REQUIRED = 3
CLUE_FRAGMENTS_REQUIRED_RARE = 5

# -- Difficulty bands (section 3) ---------------------------------------------------------------
DIFFICULTY_BANDS = ["Safe", "Standard", "Dangerous", "Forbidden"]
DIFFICULTY_RANK_OFFSET = {"Safe": -1, "Standard": 0, "Dangerous": 1, "Forbidden": 2}
DIFFICULTY_REWARD_QUALITY_PCT = {"Safe": -15, "Standard": 0, "Dangerous": 20, "Forbidden": 50}

# -- Universal rarity + rank tables (section 9) -------------------------------------------------
from .manual_data import RARITY_BASE_WEIGHTS  # noqa: E402  (shared with manual rarity — one table)

ITEM_RANK_RELATIVE_WEIGHTS = {-2: 5.0, -1: 25.0, 0: 55.0, 1: 13.0, 2: 2.0}

# -- Reward roll structure (section 9) -----------------------------------------------------------
# (guaranteed_rolls, bonus_roll_chance, bonus_roll_label)
REWARD_ROLL_STRUCTURE = {
    "minor_find": {"guaranteed": 1, "bonus_chance": 0.20},
    "encounter": {"guaranteed": 1, "bonus_chance": 0.25, "clue_chance": 0.05},
    "inheritance_room": {"guaranteed": 1, "bonus_chance": 0.15, "clue_chance": 0.10},
    "inheritance_final": {"guaranteed": 2, "bonus_chance": 0.35, "manual_chance": 0.08},
    "secret_realm_node": {"guaranteed": 1, "bonus_chance": 0.15},
    "secret_realm_boss": {"guaranteed": 2, "bonus_chance": 0.20, "named_chance": 0.10},
    "dream_stage": {"guaranteed": 1, "bonus_chance": 0.10, "hidden_line_chance": 0.10},
    "dream_completion": {"guaranteed": 2, "bonus_chance": 0.12, "unique_chance": 0.05},
}

# TESTING: a straight 30-50 Ink + 30-50 Dust roll, dropped into every final-chest table
# below at a generous weight so manual crafting is easy to test — much bigger and far more
# reliable than the existing recipe_fragment/unique_legacy/unique_treasure/hidden_line_repair/
# path_attainment/unique_memory_seed categories (each 2-33%, 3-10 dust only, no ink). Revert
# (or cut the weight way down) once testing is done — see discovery_gen.generate_loot's
# "manual_currency_bundle" branch and GameManager._grant_reward's "manual_currency" kind.
MANUAL_CURRENCY_BUNDLE_WEIGHT = 15.0

# -- Source-specific loot category tables (section 10) ---------------------------------------
INHERITANCE_FINAL_CHEST_TABLE = {
    "manual_page_bundle": 30.0, "complete_manual": 8.0, "signature_gu": 15.0, "weapon": 12.0,
    "armor": 10.0, "cultivation_resource": 10.0, "recipe_fragment": 8.0, "clue_or_key": 5.0,
    "unique_legacy": 2.0, "manual_currency_bundle": MANUAL_CURRENCY_BUNDLE_WEIGHT,
}
SECRET_REALM_BOSS_CHEST_TABLE = {
    "rare_material_bundle": 28.0, "spirit_stones": 18.0, "wild_gu": 17.0, "weapon": 10.0,
    "armor": 10.0, "manual_page": 10.0, "complete_manual": 2.0, "realm_key": 3.0, "unique_treasure": 2.0,
    "manual_currency_bundle": MANUAL_CURRENCY_BUNDLE_WEIGHT,
}
DREAM_REALM_COMPLETION_TABLE = {
    "high_quality_pages": 38.0, "path_attainment": 22.0, "breakthrough_page": 10.0,
    "hidden_line_repair": 8.0, "dream_gu": 7.0, "dream_material": 7.0, "complete_manual": 5.0,
    "unique_memory_seed": 3.0, "manual_currency_bundle": MANUAL_CURRENCY_BUNDLE_WEIGHT,
}
SOURCE_CATEGORY_TABLES = {
    "inheritance": INHERITANCE_FINAL_CHEST_TABLE,
    "secret_realm": SECRET_REALM_BOSS_CHEST_TABLE,
    "dream_realm": DREAM_REALM_COMPLETION_TABLE,
}

# Rarity weight modifiers applied per-source before rolling item rarity (section 9's
# "source rarity modifiers" table, expressed as relative multipliers on the base weights).
SOURCE_RARITY_MULTIPLIERS = {
    "minor_find": {"Common": 1.3, "Uncommon": 1.15},
    "encounter": {},
    "inheritance_room": {},
    "inheritance_final": {"Legendary": 1.25, "Mythic": 1.25, "Divine": 1.25, "Unique": 1.25},
    "secret_realm_boss": {"Epic": 1.15, "Legendary": 1.15, "Mythic": 1.15, "Divine": 1.15, "Unique": 1.15},
    "dream_completion": {"Mythic": 1.35, "Divine": 1.35, "Unique": 1.35},
    "forbidden": {"Legendary": 1.25, "Mythic": 1.25, "Divine": 1.25, "Unique": 1.25},
}

# -- Gu role weights by source (section 12) -------------------------------------------------
GU_ROLE_WEIGHTS_BY_SOURCE = {
    "inheritance": {
        "cultivation": 25.0, "offensive": 20.0, "defensive": 15.0, "movement": 10.0,
        "healing": 10.0, "utility": 8.0, "refinement": 7.0, "dream": 5.0,
    },
    "secret_realm": {
        "cultivation": 15.0, "offensive": 20.0, "defensive": 15.0, "movement": 10.0,
        "healing": 10.0, "utility": 10.0, "refinement": 10.0, "dream": 10.0,
    },
    "dream_realm": {
        "cultivation": 15.0, "offensive": 10.0, "defensive": 10.0, "movement": 5.0,
        "healing": 5.0, "utility": 20.0, "refinement": 10.0, "dream": 25.0,
    },
}

# -- Equipment affixes (section 13) -----------------------------------------------------------
EQUIPMENT_AFFIX_GROUPS = {
    "Cultivation": ["cultivation_gain while equipped", "manual comprehension", "reduced resource cost"],
    "Path resonance": ["+effect to pages sharing a tag", "matching Gu activation bonus"],
    "Combat": ["damage", "defense", "speed", "critical chance", "penetration", "shields"],
    "Exploration": ["+search quality", "extra clue chance", "trap detection", "secret-room chance"],
    "Realm resistance": ["heat", "poison", "dream", "soul", "time", "space resistance"],
    "Restriction": ["path-locked", "drains essence", "oath-bound", "region-weak"],
    "Set effect": ["two/three-piece inheritance set bonus"],
}
EQUIPMENT_AFFIX_COUNT = {
    "Common": (1, 1), "Uncommon": (1, 2), "Rare": (2, 2), "Epic": (2, 3),
    "Legendary": (3, 3), "Mythic": (3, 4), "Divine": (4, 4), "Unique": (4, 6),
}

# -- Dismantling values (section 15) -----------------------------------------------------------
DISMANTLE_VALUES = {
    "Common": {"ink": 1, "dust": 0, "special": None},
    "Uncommon": {"ink": 2, "dust": 1, "special": None},
    "Rare": {"ink": 4, "dust": 2, "special": "path_fragment_chance"},
    "Epic": {"ink": 8, "dust": 4, "special": "path_fragment"},
    "Legendary": {"ink": 15, "dust": 8, "special": "legacy_seal_fragment"},
    "Mythic": {"ink": 30, "dust": 15, "special": "mythic_comprehension_shard"},
    "Divine": {"ink": 60, "dust": 30, "special": "divine_law_trace"},
    "Unique": {"ink": 0, "dust": 0, "special": None},  # cannot normally dismantle
}

# -- Inheritance / secret realm / dream realm theme templates (section 4) ----------------------
# theme_for_discovery (discovery_gen.py) picks uniformly at random from whichever list
# matches the roll's discovery_type — there's no region/rank filter on top of that (a theme
# can surface for any player at any rank, same as it already worked before these entries
# existed), so the three Verdant Borderlands-themed entries appended to each list below sit
# alongside the pre-existing generic ones on equal footing rather than replacing them.
INHERITANCE_THEMES = [
    {"name": "Cave Inheritance", "rewards": "Manual pages, cultivation materials, one signature Gu.", "challenge": "Guardian beast, hidden door, formation, or resource cost."},
    {"name": "Tomb Inheritance", "rewards": "Weapons, armor, soul pages, cursed treasures.", "challenge": "Traps, resentment, undead guardians, or a moral choice."},
    {"name": "Sect Ruin", "rewards": "Large mixed loot pool and multiple partial manuals.", "challenge": "Several rooms and contribution scoring."},
    {"name": "Battlefield Legacy", "rewards": "Offensive pages, weapons, blood/sword/strength Gu.", "challenge": "Wave combat or a damage race."},
    {"name": "Refinement Inheritance", "rewards": "Gu recipes, refinement pages, cauldrons, materials.", "challenge": "Recipe puzzle, heat control, or timed refinement."},
    {"name": "Personal Legacy", "rewards": "A highly coherent named manual and signature set.", "challenge": "Aptitude, path, or achievement requirement."},
    # -- Verdant Borderlands / Qi Condensation (content expansion brief section 13, #1-3) --
    # Unlike the six generic entries above, these carry a "tags" key — the schema already
    # supported it (see manager._theme_tags_for's own .get("tags", [])), the six generic
    # ones just never used it, so this is a strict improvement (real page/reward biasing)
    # rather than a new mechanic.
    {
        "name": "Blood Fang Hunter's Inheritance", "tags": ["blood", "strength", "movement"],
        "rewards": "Blood/strength-path pages, a shot at the shared Tier 1 Gu pool, and a trophy currency drop.",
        "challenge": "Track three false trails to find the real one, then face a guardian Blood Fang Wolf.",
    },
    {
        "name": "Moon Rabbit Hidden Burrow", "tags": ["moon", "luck", "movement"],
        "rewards": "Moon/luck-path pages and a boosted clue-fragment chance.",
        "challenge": "Choose the right door by lunar phase, then face a Moon-Eared Rabbit illusion guardian.",
    },
    {
        "name": "Grave Moss Hermit's Cave", "tags": ["soul", "earth"],
        "rewards": "Soul/earth-path pages and grave-touched materials.",
        "challenge": "Resist the whispers of the burial tablets, then a swarm of Grave-Moss Corpse Beetles.",
    },
    # -- Hundred Beast Mountains / Foundation Establishment (brief section 13, #4-6) --
    {
        "name": "Thunderhorn Ancestor's Trial", "tags": ["lightning", "strength", "earth"],
        "rewards": "Lightning/strength-path pages, a shot at Thunderhorn Gu, and a real chance at the Thunderhorn War Drum.",
        "challenge": "Endure a series of escalating thunder strikes, then face a guardian Thunderhorn Yak.",
    },
    {
        "name": "Ghost-Eyed Tiger King's Den", "tags": ["soul", "wisdom", "strength"],
        "rewards": "Soul/wisdom-path pages and a shot at Ghost Eye Gu.",
        "challenge": "Tell reality apart from hunting illusions, then face a guardian Ghost-Eyed White Tiger.",
    },
    {
        "name": "Thousand Web Poison Matriarch Legacy", "tags": ["poison", "formation", "restriction"],
        "rewards": "Poison/formation-path pages and a shot at Venom Web Gu.",
        "challenge": "Navigate the web nodes without waking every guardian at once.",
    },
    # -- Crimson Furnace Province / Core Formation (brief section 13, #7-9) --
    {
        "name": "Crimson Furnace Grandmaster's Tomb", "tags": ["fire", "refinement", "metal"],
        "rewards": "Fire/refinement-path pages, a boosted complete-manual chance, and Star-Iron materials.",
        "challenge": "Maintain the tomb's own furnace balance, then face a guardian Brass Furnace Hound.",
    },
    {
        "name": "Living Pill Rebellion Record", "tags": ["pill", "wisdom", "soul"],
        "rewards": "Wisdom/soul-path pages, alchemy recipes, and a shot at Living Pill Core.",
        "challenge": "Decide whether the sentient pill at the record's heart is a person or a resource — the reward changes with the choice.",
    },
    {
        "name": "Star-Iron Devourer's Sealed Stomach", "tags": ["metal", "food", "space"],
        "rewards": "Metal-path pages, rare ore, and a shot at Star-Iron Stomach Gu.",
        "challenge": "Survive inside the beast's own spatial stomach long enough to find the way back out.",
    },
]
SECRET_REALM_THEMES = [
    {"name": "Blazing Furnace Valley", "loot": "Fire materials, weapon ore, fire-path Gu.", "hazard": "Heat stacks and equipment durability.", "tags": ["fire"]},
    {"name": "Moonlit Jade Forest", "loot": "Wood/moon pages, healing Gu, armor materials.", "hazard": "Illusions and pathfinding.", "tags": ["wood", "moon"]},
    {"name": "Blood Tide Marsh", "loot": "Blood materials, beast Gu, body pages.", "hazard": "Corruption and escalating enemy aggression.", "tags": ["blood"]},
    {"name": "Starfall Grotto", "loot": "Wisdom/star pages, rare ore, formation tools.", "hazard": "Changing rules each room.", "tags": ["wisdom", "star"]},
    {"name": "Soul Mist Battlefield", "loot": "Soul pages, memory shards, ghost Gu.", "hazard": "Soul damage and false reward choices.", "tags": ["soul"]},
    {"name": "Time-Fractured Garden", "loot": "Growth resources and cooldown items.", "hazard": "Limited turns or rapidly aging resources.", "tags": ["time"]},
    # -- Verdant Borderlands / Qi Condensation (brief section 14.1-14.2, plus one original
    # entry in the same style to round out the region's own trio — the brief's starter set
    # only hand-authored 6 secret realms total across every region, not 3 per region).
    {
        "name": "Moonlit Spirit Garden", "tags": ["moon", "luck"],
        "loot": "Herbs, moon-path pages, and luck/search-leaning rewards. Boss: Moonwell Guardian Hare.",
        "hazard": "Illusions and misleading paths under the moonlight.",
    },
    {
        "name": "Poison Frog Marsh", "tags": ["poison", "water"],
        "loot": "Poison materials and alchemy ingredients. Boss: Jade Shell Toad Patriarch.",
        "hazard": "Toxic mist that punishes lingering too long in one spot.",
    },
    {
        "name": "Hollow Grave Descent", "tags": ["soul", "earth"],
        "loot": "Grave-touched materials and soul/earth-path pages. Boss: Grave-Moss Beetle Matriarch.",
        "hazard": "Residual qi that saps stamina the deeper you go.",
    },
    # -- Hundred Beast Mountains / Foundation Establishment — the brief doesn't hand-name a
    # secret realm for this region either, so these are original entries in the same style,
    # tied to this region's own hunt monsters (same precedent as Verdant Borderlands' own
    # Hollow Grave Descent).
    {
        "name": "Granite Cliff Aerie", "tags": ["earth", "wind"],
        "loot": "Ore and stone materials, earth/wind-path pages. Boss: Ironbeak Vulture Matriarch.",
        "hazard": "Sheer drops and sudden updrafts that punish careless footing.",
    },
    {
        "name": "Storm Plateau Descent", "tags": ["lightning", "earth"],
        "loot": "Thunderhorn materials and lightning-path pages. Boss: Thunderhorn Herd Elder.",
        "hazard": "Rolling lightning strikes that intensify the deeper you go.",
    },
    {
        "name": "Web-Choked Ravine", "tags": ["poison", "formation"],
        "loot": "Venom materials and poison/formation-path pages. Boss: Venom Mist Spider Matriarch.",
        "hazard": "Poisoned mist and half-hidden webs strung across every path.",
    },
    # -- Crimson Furnace Province / Core Formation (brief section 14.3 hand-names Star-Iron
    # Meteor Cave for this exact region — ties directly to this region's own Star-Iron
    # Devouring Worm elite hunt; the other two are original entries in the same style).
    {
        "name": "Star-Iron Meteor Cave", "tags": ["metal", "star"],
        "loot": "Ore, blacksmith materials, metal-path pages, artifact fragments. Boss: Star-Iron Devouring Worm.",
        "hazard": "Magnetic tunnels that pull loose gear toward the walls.",
    },
    {
        "name": "Molten Furnace Depths", "tags": ["fire", "metal"],
        "loot": "Furnace materials and fire/metal-path pages. Boss: Crimson Furnace Lion King's Ashmane Kin.",
        "hazard": "Rising ambient heat that punishes lingering in any one chamber too long.",
    },
    {
        "name": "Living Pill Alchemy Vault", "tags": ["pill", "wisdom"],
        "loot": "Rare herbs, alchemy recipes, pill-path pages. Boss: Awakened Furnace Pill.",
        "hazard": "Half-finished pills that go off unpredictably if disturbed.",
    },
]
DREAM_REALM_FORMS = [
    {"name": "Life Reenactment", "reward": "Path attainment and coherent page bundle.", "failure": "Dream soul damage; retain partial insight.", "tags": ["human", "soul"]},
    {"name": "Technique Comprehension", "reward": "One high-quality technique or breakthrough page.", "failure": "Technique becomes flawed or sealed until repaired.", "tags": ["wisdom"]},
    {"name": "Emotional Trial", "reward": "Will, wisdom, soul, or heart-related page.", "failure": "Temporary debuff based on the failed emotion.", "tags": ["emotion", "soul"]},
    {"name": "Historic Battle", "reward": "Combat page, weapon memory, killer-move fragment.", "failure": "Must retry from a checkpoint.", "tags": ["sword", "blade"]},
    {"name": "Refinement Dream", "reward": "Recipe page, refinement insight, rare Gu embryo.", "failure": "Materials inside the dream are lost.", "tags": ["refinement"]},
    # -- Verdant Borderlands / Qi Condensation (brief section 15.1-15.2, plus one original
    # entry completing the region's own graveyard thread alongside Grave Moss Hermit's Cave
    # and Hollow Grave Descent above).
    {
        "name": "The Hunter Who Returned Alone", "tags": ["blood", "strength"],
        "reward": "Blood-path pages and insight, with a hidden line based on honesty or ruthlessness.",
        "failure": "Dream soul damage; retain partial insight.",
    },
    {
        "name": "The Moon Rabbit's Last Night", "tags": ["moon", "luck", "movement"],
        "reward": "Movement/luck-path pages and clue fragments, lived from the hunted beast's own side.",
        "failure": "Dream soul damage; retain partial insight.",
    },
    {
        "name": "The Gravekeeper's Long Watch", "tags": ["soul", "earth"],
        "reward": "Soul/earth-path pages and path attainment, for standing a long, quiet watch over the dead.",
        "failure": "Dream soul damage; retain partial insight.",
    },
    # -- Hundred Beast Mountains / Foundation Establishment — original entries in the same
    # style, tied to this region's own monsters (the brief doesn't hand-name a dream realm
    # for this region either).
    {
        "name": "The Tiger King's Last Hunt", "tags": ["soul", "strength"],
        "reward": "Soul/strength-path pages and path attainment, lived from the ghost tiger's own final hunt.",
        "failure": "Dream soul damage; retain partial insight.",
    },
    {
        "name": "The Beast Tamer's Betrayal", "tags": ["strength", "restriction"],
        "reward": "Strength/restriction-path pages and insight, with a hidden line depending on whether you let the beasts go.",
        "failure": "Dream soul damage; retain partial insight.",
    },
    {
        "name": "The Herd's Long Migration", "tags": ["earth", "movement"],
        "reward": "Earth/movement-path pages and clue fragments, lived as part of the herd itself.",
        "failure": "Dream soul damage; retain partial insight.",
    },
    # -- Crimson Furnace Province / Core Formation (brief section 15.3 hand-names Furnace
    # City Sacrifice for this region; the other two are original entries in the same style).
    # Furnace City Sacrifice deliberately has no single "correct" choice, per the brief's
    # own explicit framing — its reward text reflects that instead of implying one exists.
    {
        "name": "Furnace City Sacrifice", "tags": ["fire", "refinement"],
        "reward": "Refinement-path pages and insight, weighted by completion, consistency, and willingness to accept the pill's flaws — not by which choice you make.",
        "failure": "Dream soul damage; retain partial insight.",
    },
    {
        "name": "The Devourer's Long Hunger", "tags": ["metal", "food"],
        "reward": "Metal/food-path pages and clue fragments, lived from inside the tunnel-worm's own slow, patient hunger.",
        "failure": "Dream soul damage; retain partial insight.",
    },
    {
        "name": "The Pride's Last Ember", "tags": ["fire", "strength"],
        "reward": "Fire/strength-path pages and path attainment, lived as the furnace pride's own aging ruler.",
        "failure": "Dream soul damage; retain partial insight.",
    },
]

# -- World region discovery themes (/region -- game/world_regions.py) --------------------------
# Battlefields and region dream realms are found only via a /mine, /gather, /explore, /hunt,
# or /raid action taken while standing in one of the five mortal world regions (see
# GameManager._maybe_trigger_region_discovery) -- a separate discovery source from /search's
# own inheritance/secret_realm/dream_realm rolls above, with their own resolution flow
# (battlefield_view.BattlefieldView / region_dream_realm_view.RegionDreamRealmView) rather
# than the room-by-room DiscoveryView loop.
BATTLEFIELD_THEMES = [
    {"name": "Forgotten Border Skirmish", "tags": ["blood", "strength"]},
    {"name": "Bandit War-Camp Ruins", "tags": ["blood", "restriction"]},
    {"name": "Sunken Warband's Last Stand", "tags": ["water", "blood"]},
    {"name": "Sand-Buried Legion Ground", "tags": ["earth", "strength"]},
    {"name": "Broken Watchtower Line", "tags": ["metal", "formation"]},
]

# Each theme names which stat the trial checks (matches combat.py's own stat keys) -- "dream
# realms are stat checks checking if the cultivator's speed, attack, defense, or luck is good
# enough for the reward."
REGION_DREAM_REALM_THEMES = [
    {"name": "Trial of the Swift Current", "stat": "spd_stat", "tags": ["water", "movement"]},
    {"name": "Trial of the Unbroken Blade", "stat": "atk_stat", "tags": ["blood", "strength"]},
    {"name": "Trial of the Standing Mountain", "stat": "def_stat", "tags": ["earth"]},
    {"name": "Trial of the Wandering Star", "stat": "luck_stat", "tags": ["star", "moon"]},
]

# -- Room / event / stage tables (section 14) ---------------------------------------------------
INHERITANCE_ROOM_TABLE = {
    "Collapsed Archive": 18.0, "Guardian Chamber": 18.0, "Formation Gate": 14.0,
    "Medicine Garden": 12.0, "Trial of Will": 10.0, "Refinement Room": 10.0,
    "False Inheritance": 8.0, "Secret Chamber": 6.0, "Author's Final Message": 4.0,
}
SECRET_REALM_EVENT_TABLE = {
    "Resource Node": 25.0, "Native Beast": 20.0, "Environmental Hazard": 15.0,
    "Realm Spirit Bargain": 10.0, "Rival Explorer": 10.0, "Law Distortion": 8.0,
    "Hidden Habitat": 7.0, "Realm Core Chamber": 5.0,
}
DREAM_REALM_STAGE_TABLE = {
    "Memory Choice": 25.0, "Technique Imitation": 20.0, "Identity Concealment": 15.0,
    "Emotional Pressure": 15.0, "Historic Combat": 15.0, "Refinement Puzzle": 10.0,
}
# How many rooms/events/stages a discovery has before its final chest.
DISCOVERY_STEP_COUNT = {"inheritance": 3, "secret_realm": 3, "dream_realm": 2}

# -- Cultivation bonus soft cap (section 18) -----------------------------------------------------
# Above the soft cap, each further 1% of PRINTED manual cultivation bonus only contributes
# EFFECTIVE_PCT_ABOVE_SOFT_CAP of a percent of real effect — see manager.py's application.
# 3x the original per-rank values across the board (manual_bonus is now multiplicative against
# qi_multiplier/buff_bonus/character_bonus rather than folded into the same additive sum — see
# database.py's settle_qi/get_qi_status — so best-in-slot manuals were still landing well under
# a meaningful chunk of a heavily-stacked player's total rate even with that fix; a uniform 3x
# was chosen over a flat/absolute bump so every realm rank keeps the exact same relative
# headroom above its OLD cap, not just the low ranks that used to bind).
CULTIVATION_SOFT_CAP_BY_PLAYER_RANK = {
    1: 30, 2: 48, 3: 72, 4: 102, 5: 135, 6: 174, 7: 216,
}
CULTIVATION_HARD_CAP_BY_PLAYER_RANK = {
    1: 45, 2: 72, 3: 108, 4: 150, 5: 195, 6: 246, 7: 300,
}
EFFECTIVE_PCT_ABOVE_SOFT_CAP = 0.35
