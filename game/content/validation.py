"""
Content validator (content expansion brief, section 25) — cheap, import-time-safe sanity
checks over the catalogs content modules feed into. Returns a flat list of human-readable
error strings; an empty list means everything checked out. Run standalone via:

    python -m game.content.validation

Covers monsters (hunt pools + raid groups), discovery themes (inheritance/secret realm/
dream realm), regions, and manual pages so far — extend validate_all_content further as new
content types get their own batches, per the brief's own "work in batches" instruction.
"""

from typing import List


def validate_monsters() -> List[str]:
    from .. import monsters as monsters_module
    from ..equipment import EQUIPMENT
    from ..items import ITEMS

    # A drop can name either a generic Item (ITEMS) or a piece of static Equipment/Gu
    # (EQUIPMENT, e.g. TIER_1_GU_COMMON_POOL's "Ironhide Boar Gu (Common)") — both are valid
    # "real item" references as far as db.add_item is concerned, so both catalogs count.
    known_items = set(ITEMS) | set(EQUIPMENT)

    errors: List[str] = []
    # Two SEPARATE namespaces, not one shared one: hunt-pool monster names all merge into
    # the flat MONSTERS dict (a collision there silently shadows one entry), and raid main-
    # boss names all merge into BOSSES/BOSS_GROUPS the same way — but a raid's own MINIS
    # (group[1:]) are never looked up by name in any dict (just iterated as a list), so they
    # don't need globally-unique names and reusing a hunt monster's name for one isn't a bug.
    seen_hunt_names = set()
    seen_boss_names = set()

    for realm_index, pool in monsters_module.HUNT_MONSTERS_BY_REALM.items():
        if not pool:
            errors.append(f"HUNT_MONSTERS_BY_REALM[{realm_index}] has no monsters.")
        for monster in pool:
            _check_duplicate(monster, f"hunt realm {realm_index}", errors, seen_hunt_names, "MONSTERS")
            _validate_one_monster(monster, f"hunt realm {realm_index}", errors, known_items)

    for realm_index, groups in monsters_module.RAID_GROUPS_BY_REALM.items():
        if not groups:
            errors.append(f"RAID_GROUPS_BY_REALM[{realm_index}] has no raid groups at all.")
        for group_idx, group in enumerate(groups):
            if not group:
                errors.append(f"RAID_GROUPS_BY_REALM[{realm_index}][{group_idx}] has no enemies.")
            for i, monster in enumerate(group):
                context = f"raid realm {realm_index} group {group_idx}" + (" (main boss)" if i == 0 else " (mini)")
                if i == 0:
                    _check_duplicate(monster, context, errors, seen_boss_names, "BOSSES/BOSS_GROUPS")
                _validate_one_monster(monster, context, errors, known_items)
            if group and group[0].name not in monsters_module.BOSS_GROUPS:
                errors.append(f"Raid group main boss '{group[0].name}' (realm {realm_index} group {group_idx}) missing from BOSS_GROUPS.")

    return errors


def validate_white_heaven() -> List[str]:
    """Checks game/content/monsters/white_heaven.py's fixed-difficulty roster -- reuses the
    exact same per-monster checks validate_monsters() uses, but against
    WHITE_HEAVEN_HUNT_MONSTERS/WHITE_HEAVEN_RAID_GROUP directly, since those are
    deliberately NOT folded into HUNT_MONSTERS_BY_REALM/RAID_GROUPS_BY_REALM (fixed
    difficulty, not realm-indexed) and so validate_monsters()'s own realm-keyed loops never
    see them at all."""
    from .. import monsters as monsters_module
    from ..equipment import EQUIPMENT
    from ..items import ITEMS

    known_items = set(ITEMS) | set(EQUIPMENT)
    errors: List[str] = []
    seen_names = set()

    if not monsters_module.WHITE_HEAVEN_HUNT_MONSTERS:
        errors.append("[white_heaven] WHITE_HEAVEN_HUNT_MONSTERS has no monsters.")
    for monster in monsters_module.WHITE_HEAVEN_HUNT_MONSTERS:
        _check_duplicate(monster, "white_heaven hunt", errors, seen_names, "MONSTERS")
        _validate_one_monster(monster, "white_heaven hunt", errors, known_items)
        if monster.name not in monsters_module.MONSTERS:
            errors.append(f"[white_heaven] '{monster.name}' missing from the flat MONSTERS dict — HuntView's lookup would fail.")

    group = monsters_module.WHITE_HEAVEN_RAID_GROUP
    if not group:
        errors.append("[white_heaven] WHITE_HEAVEN_RAID_GROUP has no enemies.")
    for i, monster in enumerate(group):
        context = "white_heaven raid" + (" (main boss)" if i == 0 else " (mini)")
        if i == 0:
            _check_duplicate(monster, context, errors, seen_names, "BOSSES/BOSS_GROUPS")
        _validate_one_monster(monster, context, errors, known_items)
    if group and group[0].name not in monsters_module.BOSS_GROUPS:
        errors.append(f"[white_heaven] raid main boss '{group[0].name}' missing from BOSS_GROUPS — RaidView's lookup would fail.")

    return errors


def validate_black_heaven() -> List[str]:
    """Checks game/content/monsters/black_heaven.py's own battle-bubble roster -- reuses the
    same per-monster checks validate_monsters()/validate_white_heaven() use, but against
    ALL_MONSTERS_BY_RARITY directly. Unlike White Heaven's own hunt/raid roster, this one is
    NEVER registered into monsters.MONSTERS/BOSS_GROUPS at all (roll_black_heaven_battle_
    monster reads straight from ALL_MONSTERS_BY_RARITY by rarity tier, not by name lookup),
    so the dict-membership checks validate_white_heaven() does don't apply here -- this is
    also net-new validator coverage for the underlying rarity-tiered-roster pattern:
    content/monsters/blood_sea_ancestor.py (Inheritance Ground's own battle-bubble roster,
    the template this file's own shape was copied from) has never had validator coverage
    either."""
    from .monsters import black_heaven as black_heaven_monsters
    from ..equipment import EQUIPMENT
    from ..items import ITEMS

    known_items = set(ITEMS) | set(EQUIPMENT)
    errors: List[str] = []
    seen_names = set()

    for rarity, roster in black_heaven_monsters.ALL_MONSTERS_BY_RARITY.items():
        if not roster:
            errors.append(f"[black_heaven] ALL_MONSTERS_BY_RARITY['{rarity}'] has no monsters.")
        for monster in roster:
            context = f"black_heaven battle ({rarity})"
            _check_duplicate(monster, context, errors, seen_names, "ALL_MONSTERS_BY_RARITY")
            _validate_one_monster(monster, context, errors, known_items)
            if black_heaven_monsters.RARITY_BY_NAME.get(monster.name) != rarity:
                errors.append(f"[black_heaven] '{monster.name}': RARITY_BY_NAME doesn't map back to '{rarity}' — grant_black_heaven_battle_loot's rarity lookup would misfire.")

    return errors


def _check_duplicate(monster, context: str, errors: List[str], seen_names: set, dict_name: str) -> None:
    name = getattr(monster, "name", None)
    if name and name in seen_names:
        errors.append(f"[{context}] duplicate name '{name}' — {dict_name} would silently drop one.")
    if name:
        seen_names.add(name)


def _validate_one_monster(monster, context: str, errors: List[str], known_items: set) -> None:
    name = getattr(monster, "name", None)
    if not name:
        errors.append(f"[{context}] a monster has no name.")
        return

    for stat in ("hp", "atk_stat", "str_stat", "def_stat", "spd_stat", "qi_stat"):
        value = getattr(monster, stat, None)
        if value is None or value <= 0:
            errors.append(f"[{context}] '{name}': {stat}={value} must be positive.")
    if getattr(monster, "luck_stat", 0) < 0:
        errors.append(f"[{context}] '{name}': luck_stat must be >= 0.")

    if not (1 <= getattr(monster, "gu_rank", 0)):
        errors.append(f"[{context}] '{name}': gu_rank must be >= 1.")

    weight = getattr(monster, "encounter_weight", None)
    if weight is None or weight <= 0:
        errors.append(f"[{context}] '{name}': encounter_weight must be positive (it's a random.choices weight).")

    ability = getattr(monster, "ability", None)
    if ability is None:
        errors.append(f"[{context}] '{name}': missing ability.")
    else:
        if ability.str_multiplier <= 0:
            errors.append(f"[{context}] '{name}': ability.str_multiplier must be positive.")
        if not (0.0 <= ability.lifesteal_percent <= 1.0):
            errors.append(f"[{context}] '{name}': ability.lifesteal_percent must be within [0, 1].")

    if not monster.drops and context.startswith("hunt"):
        errors.append(f"[{context}] '{name}': no drops at all — a hunt with zero reward for winning.")

    for entry in monster.drops:
        if not (0.0 <= entry.chance <= 1.0):
            errors.append(f"[{context}] '{name}': drop chance {entry.chance} for {entry.item_name or entry.pool} is outside [0, 1].")
        if entry.quantity < 1:
            errors.append(f"[{context}] '{name}': drop quantity {entry.quantity} must be >= 1.")
        if entry.item_name is None and not entry.pool:
            errors.append(f"[{context}] '{name}': a DropEntry has neither item_name nor pool set.")
        if entry.item_name and entry.item_name not in known_items:
            errors.append(f"[{context}] '{name}': drop references unknown item '{entry.item_name}' (not in items.ITEMS or equipment.EQUIPMENT).")
        if entry.pool:
            if not entry.pool:
                errors.append(f"[{context}] '{name}': a DropEntry's pool is empty.")
            for pool_item in entry.pool:
                if pool_item not in known_items:
                    errors.append(f"[{context}] '{name}': pool drop references unknown item '{pool_item}' (not in items.ITEMS or equipment.EQUIPMENT).")


def validate_discoveries() -> List[str]:
    """Checks search_data's INHERITANCE_THEMES/SECRET_REALM_THEMES/DREAM_REALM_FORMS —
    unique names within each list (theme_for_discovery just does rng.choice, so a duplicate
    name is only a display ambiguity, not a crash, but still worth flagging), required
    flavor-text keys present, and every tag a real path tag manual pages can actually carry
    (an unknown tag would silently never match any page in _roll_pages)."""
    from . import regions as regions_module
    from .. import manual_data

    errors: List[str] = []
    known_tags = set(manual_data.ALL_PATH_TAGS)

    tables = {
        "INHERITANCE_THEMES": (_search_data().INHERITANCE_THEMES, ("rewards", "challenge")),
        "SECRET_REALM_THEMES": (_search_data().SECRET_REALM_THEMES, ("loot", "hazard")),
        "DREAM_REALM_FORMS": (_search_data().DREAM_REALM_FORMS, ("reward", "failure")),
    }
    for table_name, (entries, required_keys) in tables.items():
        seen_names = set()
        for entry in entries:
            name = entry.get("name")
            if not name:
                errors.append(f"[{table_name}] an entry has no name.")
                continue
            if name in seen_names:
                errors.append(f"[{table_name}] duplicate theme name '{name}'.")
            seen_names.add(name)
            for key in required_keys:
                if not entry.get(key):
                    errors.append(f"[{table_name}] '{name}' is missing its '{key}' flavor text.")
            for tag in entry.get("tags", []):
                if tag not in known_tags:
                    errors.append(f"[{table_name}] '{name}' has unknown tag '{tag}' (not in manual_data.ALL_PATH_TAGS) — it will never match a page.")

    # Cross-check regions.py's own material_ids point at real, registered items — a region
    # definition drifting from the actual catalog is an easy copy/paste error to make.
    from ..items import ITEMS
    for region in regions_module.REGIONS.values():
        for material_id in region.material_ids:
            if material_id not in ITEMS:
                errors.append(f"[regions:{region.region_id}] material_id '{material_id}' not in items.ITEMS.")
        from .. import monsters as monsters_module
        for monster_name in region.hunt_monster_ids:
            if monster_name not in monsters_module.MONSTERS:
                errors.append(f"[regions:{region.region_id}] hunt_monster_id '{monster_name}' not in monsters.MONSTERS.")

    return errors


def _search_data():
    from .. import search_data
    return search_data


def validate_gu_families() -> List[str]:
    """Checks equipment.GU_FAMILIES — every quality tier present (the fusion ladder assumes
    Common..Immortal all exist), every stat_bonuses key recognized by the scoring/display
    system (an unknown key would silently score 0 and show no text in equipment_view.py's
    "Total Bonuses"/"Passive Bonuses" fields — a real item that looks like it does nothing),
    and no two families resolving to the same EQUIPMENT item name."""
    from .. import equipment

    errors: List[str] = []
    known_stat_keys = set(equipment.FOUNDATION_STAT_LABELS) | set(equipment.SPECIAL_BONUS_POWER_WEIGHTS)
    seen_item_names = set()

    for family_name, family_data in equipment.GU_FAMILIES.items():
        qualities = family_data.get("qualities", {})
        for quality in equipment.GU_QUALITY_ORDER:
            if quality not in qualities:
                errors.append(f"[gu_families] '{family_name}' is missing its '{quality}' tier — the fusion ladder assumes all 7 exist.")
                continue
            bonuses = qualities[quality]
            if not bonuses:
                errors.append(f"[gu_families] '{family_name}' ({quality}) has no stat_bonuses at all.")
            for key in bonuses:
                if key not in known_stat_keys:
                    errors.append(f"[gu_families] '{family_name}' ({quality}): unknown stat key '{key}' — won't score or display correctly.")
            item_name = equipment.gu_item_name(family_name, quality)
            if item_name in seen_item_names:
                errors.append(f"[gu_families] duplicate resulting item name '{item_name}'.")
            seen_item_names.add(item_name)
            if item_name not in equipment.EQUIPMENT:
                errors.append(f"[gu_families] '{item_name}' not found in equipment.EQUIPMENT — _register_tiered_gu() may have run before this family was merged in.")

    return errors


def validate_canon_gu() -> List[str]:
    """Checks canon_gu.CANON_GU — a gap that had zero validator coverage until now, unlike
    every other content-module catalog in this file. Duplicate names, required fields,
    sane gu_rank/drop_weight/base_power ranges, known rarity values (reuses manual_data.
    RARITY_ORDER, the same broader vocabulary accessories/discoveries already share), and
    that _FUNCTIONAL_STAT_KEY/_FUNCTIONAL_EFFECT_BY_STAR (the small set of canon Gu with a
    real passive, see canon_gu.py's own module docstring) stay internally consistent with
    each other and with a real, known stat_bonuses key."""
    from .. import canon_gu, equipment, manual_data
    from ..manager import GameManager

    errors: List[str] = []
    # equipment.SPECIAL_BONUS_POWER_WEIGHTS looks like the right source (validate_gu_families
    # uses it) but turns out to be an incomplete, separate power-SCORING table, missing 15
    # real SPECIAL_BONUS_KEYS entries (fire_burn_damage_pct, armor_penetration_pct,
    # total_damage_pct, ...) that were never added there when they were added to the real
    # pool. GameManager.SPECIAL_BONUS_KEYS is the actual authoritative "flows through
    # compute_equipment_bonuses" list. retaliation_damage_pct is allowed separately -- it's
    # root/physique/Gu-via-_trait_bonus only (HuntView/TeamBattleEngine's own local
    # _trait_bonus, not the generic SPECIAL_BONUS_KEYS pool), which White Heaven's Heavenly
    # Reflection Gu is the first Gu to use.
    known_stat_keys = set(equipment.FOUNDATION_STAT_LABELS) | set(GameManager.SPECIAL_BONUS_KEYS) | {"retaliation_damage_pct"}
    known_rarities = set(manual_data.RARITY_ORDER)
    seen_names = set()

    for gu in canon_gu.CANON_GU:
        name = gu.get("name")
        if not name:
            errors.append("[canon_gu] an entry has no 'name' at all.")
            continue
        if name in seen_names:
            errors.append(f"[canon_gu] duplicate name '{name}'.")
        seen_names.add(name)

        for field in ("gu_rank", "path", "role", "rarity", "drop_weight", "base_power", "is_passive", "description", "effect_text"):
            if field not in gu:
                errors.append(f"[canon_gu] '{name}' is missing required field '{field}'.")

        if "gu_rank" in gu and (not isinstance(gu["gu_rank"], int) or gu["gu_rank"] < 1):
            errors.append(f"[canon_gu] '{name}' has an invalid gu_rank {gu.get('gu_rank')!r} (must be a positive int).")
        if "drop_weight" in gu and (not isinstance(gu["drop_weight"], (int, float)) or gu["drop_weight"] < 0):
            errors.append(f"[canon_gu] '{name}' has a negative drop_weight {gu.get('drop_weight')!r}.")
        if "base_power" in gu and (not isinstance(gu["base_power"], (int, float)) or gu["base_power"] <= 0):
            errors.append(f"[canon_gu] '{name}' has a non-positive base_power {gu.get('base_power')!r}.")
        if "rarity" in gu and gu["rarity"] not in known_rarities:
            errors.append(f"[canon_gu] '{name}' has an unrecognized rarity '{gu.get('rarity')}' (expected one of {sorted(known_rarities)}).")

    # _FUNCTIONAL_STAT_KEY/_FUNCTIONAL_EFFECT_BY_STAR (the handful of canon Gu with a real,
    # wired passive rather than the generic role-power fallback) must reference real Gu,
    # real stat keys, and a full 7-entry star curve (matching equipment.GU_QUALITY_ORDER).
    star_count = len(equipment.GU_QUALITY_ORDER)
    for name, (stat_key, kind) in canon_gu._FUNCTIONAL_STAT_KEY.items():
        if name not in seen_names:
            errors.append(f"[canon_gu] _FUNCTIONAL_STAT_KEY references '{name}', which isn't in CANON_GU.")
        if kind not in ("flat", "percent"):
            errors.append(f"[canon_gu] _FUNCTIONAL_STAT_KEY['{name}']'s kind '{kind}' must be 'flat' or 'percent'.")
        if kind == "percent" and stat_key not in known_stat_keys:
            errors.append(f"[canon_gu] _FUNCTIONAL_STAT_KEY['{name}']'s stat key '{stat_key}' isn't a known stat_bonuses key.")
        if name not in canon_gu._FUNCTIONAL_EFFECT_BY_STAR:
            errors.append(f"[canon_gu] '{name}' is in _FUNCTIONAL_STAT_KEY but missing from _FUNCTIONAL_EFFECT_BY_STAR.")
        elif len(canon_gu._FUNCTIONAL_EFFECT_BY_STAR[name]) != star_count:
            errors.append(f"[canon_gu] _FUNCTIONAL_EFFECT_BY_STAR['{name}'] has {len(canon_gu._FUNCTIONAL_EFFECT_BY_STAR[name])} values, expected {star_count} (one per GU_QUALITY_ORDER star).")
    for name in canon_gu._FUNCTIONAL_EFFECT_BY_STAR:
        if name not in canon_gu._FUNCTIONAL_STAT_KEY:
            errors.append(f"[canon_gu] '{name}' is in _FUNCTIONAL_EFFECT_BY_STAR but missing from _FUNCTIONAL_STAT_KEY.")

    return errors


def validate_manual_pages() -> List[str]:
    """Checks manual_data.PAGES — unique page_id, valid category/rank, known tags/flaw ids,
    positive power_value, at least one effect, and category coverage per rank: Foundation
    and Circulation are HARD requirements (manual_gen.generate_manual requires exactly one
    of each, and MAX_GENERATION_ATTEMPTS would just quietly cap out at zero pages if a rank
    had none to offer), the other 8 categories are a softer "can this even be rolled at all"
    check — not a generation-breaking bug, but a real silent content gap (see rank1_pages.py's
    own Refinement fix, caught only once this all-10-categories check existed)."""
    from .. import manual_data

    errors: List[str] = []
    known_tags = set(manual_data.ALL_PATH_TAGS)
    known_flaws = set(manual_data.FLAWS)
    seen_ids = set()
    count_by_rank_category: dict = {}

    for page_id, page in manual_data.PAGES.items():
        if page_id in seen_ids:
            errors.append(f"[manual pages] duplicate page_id '{page_id}' — PAGES would silently drop one.")
        seen_ids.add(page_id)
        if page.page_id != page_id:
            errors.append(f"[manual pages] '{page.name}': stored under key '{page_id}' but page.page_id is '{page.page_id}'.")

        if page.category not in manual_data.PAGE_CATEGORIES:
            errors.append(f"[manual pages] '{page.name}': unknown category '{page.category}'.")
        if not (1 <= page.rank <= manual_data.MAX_MANUAL_RANK):
            errors.append(f"[manual pages] '{page.name}': rank {page.rank} outside 1-{manual_data.MAX_MANUAL_RANK}.")
        if page.power_value <= 0:
            errors.append(f"[manual pages] '{page.name}': power_value must be positive.")
        if not page.base_effects:
            errors.append(f"[manual pages] '{page.name}': has no effects at all.")
        if not page.tags:
            errors.append(f"[manual pages] '{page.name}': has no tags — it can never match a primary path or theme.")
        for tag in page.tags:
            if tag not in known_tags:
                errors.append(f"[manual pages] '{page.name}': unknown tag '{tag}' (not in manual_data.ALL_PATH_TAGS).")
        for flaw_id in page.flaw_pool:
            if flaw_id not in known_flaws:
                errors.append(f"[manual pages] '{page.name}': unknown flaw id '{flaw_id}' (not in manual_data.FLAWS).")

        count_by_rank_category[(page.rank, page.category)] = count_by_rank_category.get((page.rank, page.category), 0) + 1

    for rank in range(1, manual_data.MAX_MANUAL_RANK + 1):
        for category in ("Foundation", "Circulation"):
            if count_by_rank_category.get((rank, category), 0) == 0:
                errors.append(f"[manual pages] rank {rank} has ZERO {category} pages — generate_manual requires one and would fail/loop.")
        for category in manual_data.PAGE_CATEGORIES:
            if category in ("Foundation", "Circulation"):
                continue
            if count_by_rank_category.get((rank, category), 0) == 0:
                errors.append(f"[manual pages] rank {rank} has ZERO {category} pages — that category can never be rolled at this rank (not generation-breaking, but a real content gap).")

    return errors


# Every effect_key actually implemented somewhere in manager.py's activation dispatch /
# compute_equipment_bonuses' generic stat_bonuses pass-through / raid.py / alchemy.py — see
# accessories_data.py's own module docstring "Adaptation notes" for what each maps to.
# Hardcoded rather than derived from ITEMS itself (that would be tautological — nothing
# could ever fail the check) or from MECHANIC_COST_GUIDE (which is missing 3 of these:
# essence_restore_charges, raid_party_bonus, salvage_bonus were all added to the catalog
# without a matching cost-guide entry, a pre-existing gap this validator doesn't try to fix).
KNOWN_ACCESSORY_EFFECT_KEYS = {
    "stat", "clue_chance", "encounter_shield", "post_action_buff", "extra_loot_roll_daily",
    "loot_duplicate_daily", "defeat_ward_daily", "essence_restore_charges",
    "breakthrough_boost_daily", "search_reroll_daily", "refresh_artifact_weekly",
    "raid_party_bonus", "salvage_bonus", "unique_signature",
    # Nine-Deaths Black Pearl only (see GameManager.check_and_consume_flee_ward) -- a killing
    # blow resolves as a full flee/withdraw instead of a defeat, distinct from
    # defeat_ward_daily's own "still recorded as a defeat, just no Qi lost" shape. No
    # cooldown at all (fires unlimited times, by explicit request).
    "flee_on_defeat_unlimited",
}


def validate_accessories() -> List[str]:
    """Checks accessories_data.ITEMS — unique item_id, valid category/slot_type/rank/rarity,
    a recognized effect_key (see KNOWN_ACCESSORY_EFFECT_KEYS), and any stat_bonuses keys
    recognized by the scoring/display system (same reasoning as validate_gu_families)."""
    from .. import accessories_data as ad
    from .. import equipment

    errors: List[str] = []
    known_stat_keys = set(equipment.FOUNDATION_STAT_LABELS) | set(equipment.SPECIAL_BONUS_POWER_WEIGHTS)
    valid_slot_types = {"Ring", "Earring", "Necklace", "Bracelet", "Artifact"}
    seen_ids = set()

    for item_id, item in ad.ITEMS.items():
        if item_id in seen_ids:
            errors.append(f"[accessories] duplicate item_id '{item_id}'.")
        seen_ids.add(item_id)
        if item.item_id != item_id:
            errors.append(f"[accessories] '{item.name}': stored under key '{item_id}' but item.item_id is '{item.item_id}'.")

        if item.category not in ("Accessory", "Artifact"):
            errors.append(f"[accessories] '{item.name}': unknown category '{item.category}'.")
        if item.slot_type not in valid_slot_types:
            errors.append(f"[accessories] '{item.name}': unknown slot_type '{item.slot_type}'.")
        if not (1 <= item.rank <= 7):
            errors.append(f"[accessories] '{item.name}': rank {item.rank} outside 1-7.")
        if item.rarity not in ad.RARITY_ORDER:
            errors.append(f"[accessories] '{item.name}': unknown rarity '{item.rarity}'.")
        if item.effect_key not in KNOWN_ACCESSORY_EFFECT_KEYS:
            errors.append(f"[accessories] '{item.name}': unrecognized effect_key '{item.effect_key}'.")
        if not item.description:
            errors.append(f"[accessories] '{item.name}': missing description.")
        for key in item.stat_bonuses:
            if key not in known_stat_keys:
                errors.append(f"[accessories] '{item.name}': unknown stat_bonuses key '{key}' — won't score or display correctly.")

    return errors


# Every stat_bonuses key a root spec is allowed to use — see character_data.CharacterTraitSpec's
# own docstring for what consumes each one. Deliberately its own list rather than reusing
# equipment's known_stat_keys: several of these (herb_yield_pct, meditate_battle_qi_pct, ...)
# are root-only mechanics with no gear/Gu equivalent, and a couple of equipment's own keys
# (crit_chance_pct, dodge_chance_pct, ...) aren't valid on a root at all in Phase 1's scope.
KNOWN_ROOT_STAT_KEYS = {
    "herb_yield_pct", "mining_yield_pct", "healing_item_pct", "essence_regen_pct",
    "alchemy_success_pct", "blacksmith_success_pct", "gear_dismantle_refund_pct",
    "meditate_qi_pct", "meditate_battle_qi_pct", "breakthrough_qi_loss_reduction_pct",
    "explore_luck_bonus_flat", "flee_chance_flat", "clue_chance_bonus_pct",
    "insight_gain_pct", "empower_damage_pct",
    # Rare tier's two new families (Strength, Space) — see character_data.py's own Rare
    # section comment for why Void Root only uses one of these two rather than three keys.
    "beast_damage_pct", "beast_material_quantity_bonus_pct", "secret_realm_clue_chance_pct",
    # Epic tier's two new families (Soul/Heaven, Star/Wisdom — the latter's daily upgrade
    # charge is its own dedicated CharacterTraitSpec.daily_nothing_upgrade field, not a key
    # here) and Legendary's two new families (Heaven/cross-system, Human/adaptive).
    "death_qi_loss_reduction_pct", "dream_realm_bias_pct", "discovery_quality_bias_pct",
    "profession_study_speed_pct",
    # Mythic's Refinement family — craft_salvage_bonus_pct feeds both craft_pill and
    # craft_gear via the shared _alchemy_salvage_bonus_pct helper.
    "craft_salvage_bonus_pct",
    # Silver Thread Root (Mythic) / Ancestral Hair Root (Divine) / Long Hair Ancestor Root
    # (Unique) — feeds blacksmith.roll_gear_stats' budget directly, see GameManager.craft_gear.
    "gear_budget_bonus_pct",
}


def validate_root_specs() -> List[str]:
    """Checks character_data.ROOT_SPECS_BY_NAME — every Common/Uncommon ROOT_TIERS name has
    exactly one spec (Phase 1's own explicit scope — see ROOT_SPECS_BY_NAME's module
    docstring), every spec's stat_bonuses key is recognized (see KNOWN_ROOT_STAT_KEYS above,
    same "unknown key silently does nothing" reasoning validate_gu_families already uses),
    every tags/manual_coherence_tags entry is a real manual_data.ALL_PATH_TAGS tag, every
    manual_coherence_categories entry is a real manual_data.PAGE_CATEGORIES category, and no
    spec's own coherence bonus can exceed MANUAL_COHERENCE_BONUS_CAP on a single page (the
    cap in manual_gen.calculate_coherence only catches the SUMMED total across a whole
    manual, not one page in isolation adding more than the entire budget by itself)."""
    from .. import character_data, manual_data

    errors: List[str] = []
    known_tags = set(manual_data.ALL_PATH_TAGS)
    known_categories = set(manual_data.PAGE_CATEGORIES)

    # Every root name must be unique ACROSS tiers, not just within one — ROOT_SPECS_BY_NAME is
    # a single flat dict keyed by name with no tier component, so two tiers sharing a literal
    # name silently collide: get_root_spec(name) can only ever return one of them, regardless
    # of which tier a given player actually rolled. Caught a real instance of this pre-existing
    # bug ("Sovereign Immortal Root" listed under both Divine and Unique) while building this
    # validator — see character_data.py's Divine section for the fix.
    all_tier_names: List[str] = []
    for tier_name, tier in character_data.ROOT_TIERS.items():
        all_tier_names.extend(tier.names)
    for name in set(all_tier_names):
        if all_tier_names.count(name) > 1:
            errors.append(f"[root specs] '{name}' appears in more than one ROOT_TIERS tier — get_root_spec can't tell them apart.")

    expected_names = set()
    for tier_name in ("Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic", "Divine", "Unique", "Godly"):
        expected_names |= set(character_data.ROOT_TIERS[tier_name].names)
    spec_names = set(character_data.ROOT_SPECS_BY_NAME.keys())
    for missing in expected_names - spec_names:
        errors.append(f"[root specs] '{missing}' is a root with no CharacterTraitSpec.")
    for extra in spec_names - expected_names:
        errors.append(f"[root specs] '{extra}' has a spec but isn't in any ROOT_TIERS names list (typo?).")

    for name, spec in character_data.ROOT_SPECS_BY_NAME.items():
        if not spec.description:
            errors.append(f"[root specs] '{name}': missing description (shown in /join and /profile).")
        if not spec.stat_bonuses and not spec.manual_coherence_tags and not spec.manual_coherence_categories and not spec.fire_battle_qi_trigger_fraction:
            errors.append(f"[root specs] '{name}': has no mechanic at all (stat_bonuses/coherence/fire trigger all empty).")
        for key, value in spec.stat_bonuses.items():
            if key not in KNOWN_ROOT_STAT_KEYS:
                errors.append(f"[root specs] '{name}': unknown stat_bonuses key '{key}' — won't be read by any consumer.")
            if key in ("cultivation_speed_pct", "breakthrough_chance_pct"):
                errors.append(f"[root specs] '{name}': '{key}' belongs on the shared ROOT_TIERS package, not a per-name spec — would double-count.")
        for tag in spec.tags:
            if tag not in known_tags:
                errors.append(f"[root specs] '{name}': tags entry '{tag}' isn't a known manual_data.ALL_PATH_TAGS tag.")
        for tag, bonus in spec.manual_coherence_tags.items():
            if tag not in known_tags:
                errors.append(f"[root specs] '{name}': manual_coherence_tags key '{tag}' isn't a known manual_data.ALL_PATH_TAGS tag.")
            if bonus > character_data.MANUAL_COHERENCE_BONUS_CAP:
                errors.append(f"[root specs] '{name}': manual_coherence_tags['{tag}']={bonus} alone exceeds MANUAL_COHERENCE_BONUS_CAP.")
        for category, bonus in spec.manual_coherence_categories.items():
            if category not in known_categories:
                errors.append(f"[root specs] '{name}': manual_coherence_categories key '{category}' isn't a known manual_data.PAGE_CATEGORIES category.")
            if bonus > character_data.MANUAL_COHERENCE_BONUS_CAP:
                errors.append(f"[root specs] '{name}': manual_coherence_categories['{category}']={bonus} alone exceeds MANUAL_COHERENCE_BONUS_CAP.")
        if spec.fire_battle_qi_trigger_fraction and not (0.0 < spec.fire_battle_qi_trigger_fraction <= 1.0):
            errors.append(f"[root specs] '{name}': fire_battle_qi_trigger_fraction={spec.fire_battle_qi_trigger_fraction} must be within (0, 1].")

    return errors


# Every stat_bonuses key a physique spec is allowed to use. Reuses several root-system keys
# directly (death_qi_loss_reduction_pct, dream_realm_bias_pct, beast_damage_pct,
# mining_yield_pct, healing_item_pct, meditate_qi_pct, flee_chance_flat, empower_damage_pct —
# all already in KNOWN_ROOT_STAT_KEYS, folded in through the same _trait_bonus/
# compute_equipment_bonuses pipeline a root's own bonus goes through) plus the Common
# physique tier's own new keys.
KNOWN_PHYSIQUE_ONLY_STAT_KEYS = {
    "guard_stack_def_pct", "dodge_momentum_str_bonus_pct", "every_third_attack_bonus_pct",
    "battle_qi_regen_bonus_pct", "first_gu_use_discount_flat", "high_hp_damage_reduction_pct",
    "encounter_start_adaptive_stat_pct", "post_hunt_heal_pct", "guard_or_potion_qi_restore_pct",
    # Uncommon/Rare tier's new families (Moonlight, Thunder Muscle, Phoenix Feather, Void,
    # Immortal Blood — Star family reuses encounter_start_adaptive_stat_pct above).
    "gu_miss_qi_refund_pct", "first_empower_discount_flat", "low_hp_str_pct_bonus",
    "kill_qi_restore_pct", "flee_reroll_once", "great_realm_vigor_buff_pct",
    # Heavenly Solar/Lunar Physique (Unique) — see hunt.py/raid.py's per-encounter stack
    # counters, feeding combat.resolve_attack's damage_pct_bonus/armor_penetration_pct.
    # ally_def_aura_pct/lunar_aoe_attacks are raid-only (no meaning in hunt.py's solo fights) —
    # see RaidView._attacker_stats' ally-scan and _resolve_round's per-attack target list.
    "solar_stack_damage_pct", "lunar_stack_armor_pen_pct", "ally_def_aura_pct", "lunar_aoe_attacks",
    # Blazing Glory Sunfire / Immovable Mountain Physique (Unique) — see hunt.py/raid.py's
    # new burn-tick state (mirrors Fire Dao Path's own) and retaliation handling (mirrors
    # Iron Skin's own guard-stack shape). Blood Sea Demon Physique's lifesteal_percent/
    # low_hp_str_pct_bonus need no new key here — both already exist above.
    "sunfire_burn_max_hp_pct", "retaliation_damage_pct",
}


def validate_physique_specs() -> List[str]:
    """Checks character_data.PHYSIQUE_SPECS_BY_NAME — every PHYSIQUE_TIERS name (Common
    through Unique — the full ladder, mirroring the completed root ladder) has a spec, every
    spec's stat_bonuses key is recognized (reused root keys, reused pre-existing equipment/
    manual keys via equipment.SPECIAL_BONUS_POWER_WEIGHTS, OR KNOWN_PHYSIQUE_ONLY_STAT_KEYS),
    and no physique name collides with another PHYSIQUE_TIERS tier (same class of bug the
    root ladder's own validator caught once already)."""
    from .. import character_data, equipment

    errors: List[str] = []
    known_keys = KNOWN_ROOT_STAT_KEYS | KNOWN_PHYSIQUE_ONLY_STAT_KEYS | set(equipment.SPECIAL_BONUS_POWER_WEIGHTS)

    all_tier_names: List[str] = []
    for tier in character_data.PHYSIQUE_TIERS.values():
        all_tier_names.extend(tier.names)
    for name in set(all_tier_names):
        if all_tier_names.count(name) > 1:
            errors.append(f"[physique specs] '{name}' appears in more than one PHYSIQUE_TIERS tier — get_physique_spec can't tell them apart.")

    expected_names = set(all_tier_names)
    spec_names = set(character_data.PHYSIQUE_SPECS_BY_NAME.keys())
    for missing in expected_names - spec_names:
        errors.append(f"[physique specs] '{missing}' is a physique with no CharacterTraitSpec.")
    for extra in spec_names - expected_names:
        errors.append(f"[physique specs] '{extra}' has a spec but isn't in any PHYSIQUE_TIERS names list (typo?).")

    # Physiques whose entire mechanic is a direct name check elsewhere in the codebase
    # (no stat_bonuses key involved) rather than the shared stat-bonus pipeline — e.g.
    # Primordial Origin Body's dual-stat grant on every Great Realm crossing, coded directly
    # in GameManager.attempt_breakthrough. Mirrors the same class of exception the root
    # ladder gets for free via its dedicated fire_battle_qi_trigger_fraction/daily_nothing_
    # upgrade fields — physiques have no such fields, so this explicit allowlist stands in.
    BESPOKE_MECHANIC_PHYSIQUE_NAMES = {"Primordial Origin Body", "Godly Physique"}

    for name, spec in character_data.PHYSIQUE_SPECS_BY_NAME.items():
        if not spec.description:
            errors.append(f"[physique specs] '{name}': missing description (shown in /join and /profile).")
        if not spec.stat_bonuses and name not in BESPOKE_MECHANIC_PHYSIQUE_NAMES:
            errors.append(f"[physique specs] '{name}': has no mechanic at all.")
        for key, value in spec.stat_bonuses.items():
            # Unlike a root spec, a physique spec IS allowed to carry a foundation-stat key
            # (str_pct/spd_pct/...) — that's how chargen.compute_final_stats' physique_spec
            # parameter is meant to be used eventually (e.g. Swift Foot Body's own spd_pct),
            # it just isn't used by any Common-tier family yet. Only genuinely unknown keys
            # (typos, or a key no consumer reads) are flagged.
            known_foundation_keys = {"str_pct", "atk_pct", "hp_pct", "spd_pct", "def_pct", "qi_pct", "luck_flat"}
            if key not in known_keys and key not in known_foundation_keys:
                errors.append(f"[physique specs] '{name}': unknown stat_bonuses key '{key}' — won't be read by any consumer.")

    return errors


def validate_gu_pet_content() -> List[str]:
    """Checks game/gu_pet.py's static content (see /gu_pet): GU_PET_RANK_SCALING/
    GU_PET_RANK_REQUIRED/GU_PET_RANK_TO_RARITY all cover every rank 1-7 with sane,
    monotonically non-decreasing values; GU_PET_RANK_REQUIRED indexes real professions.RANKS
    entries; SATIETY_BANDS partitions [0, 100] with no gaps; every SPECIES entry has real
    content and a recognized Path; and every stat_bonuses-shaped key this module can ever
    actually produce (CATEGORY_STAT_KEYS, COMBAT_SPECIALTY_BASE_VALUES, every real
    roll_specialty_bonus output) is a key some consumer actually reads -- either
    GameManager.SPECIAL_BONUS_KEYS (compute_equipment_bonuses' generic pool, mirroring
    validate_canon_gu's own known_stat_keys source) or one of the two _trait_bonus-style keys
    (gear_budget_bonus_pct/manual_rarity_bonus_pct) consumed directly at craft_gear/
    assemble_manual via GameManager._gu_pet_cultivation_bonus."""
    import random as _random

    from .. import gu_pet, professions
    from ..manager import GameManager

    errors: List[str] = []

    for rank in range(gu_pet.MIN_RANK, gu_pet.MAX_RANK + 1):
        if rank not in gu_pet.GU_PET_RANK_SCALING:
            errors.append(f"[gu pet] rank {rank} missing from GU_PET_RANK_SCALING.")
        if rank not in gu_pet.GU_PET_RANK_REQUIRED:
            errors.append(f"[gu pet] rank {rank} missing from GU_PET_RANK_REQUIRED.")
        if rank not in gu_pet.GU_PET_RANK_TO_RARITY:
            errors.append(f"[gu pet] rank {rank} missing from GU_PET_RANK_TO_RARITY.")

    prev_combat_mult, prev_required = -1, -1
    for rank in sorted(gu_pet.GU_PET_RANK_SCALING):
        scaling = gu_pet.GU_PET_RANK_SCALING[rank]
        if scaling["combat_multiplier"] < prev_combat_mult:
            errors.append(f"[gu pet] rank {rank}'s combat_multiplier ({scaling['combat_multiplier']}) is lower than a lower rank's -- should be monotonically non-decreasing.")
        prev_combat_mult = scaling["combat_multiplier"]
        for range_key in ("blacksmith_budget_bonus_range", "manual_unique_bonus_range"):
            lo, hi = scaling[range_key]
            if not (0 <= lo <= hi):
                errors.append(f"[gu pet] rank {rank}'s {range_key} ({lo}, {hi}) isn't a valid ascending non-negative range.")
        if scaling["satiety_material_tier"] != rank:
            errors.append(f"[gu pet] rank {rank}'s satiety_material_tier ({scaling['satiety_material_tier']}) doesn't match its own rank -- upkeep feeding would ask for the wrong tier.")
    for rank, required in sorted(gu_pet.GU_PET_RANK_REQUIRED.items()):
        if required < prev_required:
            errors.append(f"[gu pet] rank {rank}'s required Gu Refiner rank ({required}) is lower than a lower pet rank's requirement.")
        prev_required = required
        if not (0 <= required < len(professions.RANKS)):
            errors.append(f"[gu pet] rank {rank}'s required Gu Refiner rank index {required} is out of professions.RANKS' own range.")

    # SATIETY_BANDS must partition [0, 100] with no gaps, checked the same top-down-first-
    # match way gu_pet.satiety_band itself resolves a value.
    covered = [False] * 101
    for low, high, multiplier, label in gu_pet.SATIETY_BANDS:
        if not (0 <= low <= high <= 100):
            errors.append(f"[gu pet] SATIETY_BANDS entry '{label}' ({low}-{high}) isn't a valid range within [0, 100].")
            continue
        for v in range(low, high + 1):
            covered[v] = True
    uncovered = [v for v in range(101) if not covered[v]]
    if uncovered:
        shown = uncovered[:10]
        errors.append(f"[gu pet] SATIETY_BANDS leaves satiety value(s) uncovered: {shown}{'...' if len(uncovered) > len(shown) else ''}.")

    known_special_keys = set(GameManager.SPECIAL_BONUS_KEYS)
    trait_only_keys = {"gear_budget_bonus_pct", "manual_rarity_bonus_pct"}
    known_keys = known_special_keys | trait_only_keys | {"hp_pct"}

    for category, (primary, secondary) in gu_pet.CATEGORY_STAT_KEYS.items():
        for key in (primary, secondary):
            if key and key not in known_keys:
                errors.append(f"[gu pet] CATEGORY_STAT_KEYS['{category}']: unknown key '{key}' -- won't be read by compute_equipment_bonuses.")

    for species_key, values in gu_pet.COMBAT_SPECIALTY_BASE_VALUES.items():
        if species_key not in gu_pet.SPECIES:
            errors.append(f"[gu pet] COMBAT_SPECIALTY_BASE_VALUES references unknown species '{species_key}'.")
        for key, value in values.items():
            if key not in known_keys:
                errors.append(f"[gu pet] COMBAT_SPECIALTY_BASE_VALUES['{species_key}']: unknown key '{key}'.")
            if value <= 0:
                errors.append(f"[gu pet] COMBAT_SPECIALTY_BASE_VALUES['{species_key}']['{key}']={value} should be positive.")

    for species_key, species in gu_pet.SPECIES.items():
        if not species.name or not species.role_text or not species.emoji:
            errors.append(f"[gu pet] SPECIES['{species_key}']: missing name/role_text/emoji.")
        if species.path not in (gu_pet.PATH_COMBAT, gu_pet.PATH_CULTIVATION):
            errors.append(f"[gu pet] SPECIES['{species_key}']: path '{species.path}' isn't a recognized Path.")
        if species.path == gu_pet.PATH_CULTIVATION and species_key != gu_pet.SPECIES_UNBOUND and not species.preferred_categories:
            errors.append(f"[gu pet] SPECIES['{species_key}']: Cultivation-Path species with no preferred_categories -- crystallize()'s nearest-match can never pick it correctly.")

    # Every real roll_specialty_bonus output key, across every rank it can appear at (a fixed
    # seed keeps this deterministic -- the RNG only ever affects WHERE within a range the
    # value lands, never WHICH keys get produced). Skips a rank already flagged missing from
    # GU_PET_RANK_SCALING above -- rank_scaling(rank) would KeyError on it otherwise, and a
    # validator crashing partway through would hide every OTHER real issue behind it.
    for species_key in gu_pet.SPECIES:
        for rank in range(gu_pet.MIN_RANK, gu_pet.MAX_RANK + 1):
            if rank not in gu_pet.GU_PET_RANK_SCALING:
                continue
            for key in gu_pet.roll_specialty_bonus(species_key, rank, rng=_random.Random(0)):
                if key not in known_keys:
                    errors.append(f"[gu pet] roll_specialty_bonus('{species_key}', {rank}) produces unknown key '{key}'.")

    return errors


def validate_servants() -> List[str]:
    """Checks game/servants.py's static catalog (see /servant, admin-only preview): every
    tier 1-7 has at least one entry, every name's tier matches its SERVANTS_BY_TIER bucket,
    within_tier_weight is positive, base_stats only uses real foundation-stat keys, and every
    support_bonus_key is either a real GameManager.SPECIAL_BONUS_KEYS entry or one of
    servants.SUPPORT_KEYS_OUTSIDE_GENERIC_POOL (the yield/cultivation keys wired directly at
    their own consumption sites instead -- see GameManager._servant_yield_bonus and
    database.py's _qi_rate_components)."""
    from .. import servants
    from ..manager import GameManager

    errors: List[str] = []
    known_special_keys = set(GameManager.SPECIAL_BONUS_KEYS)
    known_stat_keys = {"str_stat", "atk_stat", "hp", "spd_stat", "def_stat", "qi_stat", "luck_stat"}

    for tier in range(1, 8):
        if not servants.SERVANTS_BY_TIER.get(tier):
            errors.append(f"[servants] Tier {tier} has no servants in SERVANTS_BY_TIER.")

    for name, servant in servants.SERVANT_CATALOG.items():
        if name not in servants.SERVANTS_BY_TIER.get(servant.tier, []):
            errors.append(f"[servants] '{name}' has tier {servant.tier} but isn't listed under SERVANTS_BY_TIER[{servant.tier}].")
        if servant.within_tier_weight <= 0:
            errors.append(f"[servants] '{name}': within_tier_weight ({servant.within_tier_weight}) should be positive.")
        for key in servant.base_stats:
            if key not in known_stat_keys:
                errors.append(f"[servants] '{name}': base_stats has unknown stat key '{key}'.")
        if servant.support_bonus_key not in known_special_keys and servant.support_bonus_key not in servants.SUPPORT_KEYS_OUTSIDE_GENERIC_POOL:
            errors.append(f"[servants] '{name}': support_bonus_key '{servant.support_bonus_key}' isn't a known SPECIAL_BONUS_KEYS entry or a SUPPORT_KEYS_OUTSIDE_GENERIC_POOL key.")

    return errors


def validate_all_content() -> List[str]:
    errors: List[str] = []
    errors.extend(validate_monsters())
    errors.extend(validate_white_heaven())
    errors.extend(validate_black_heaven())
    errors.extend(validate_discoveries())
    errors.extend(validate_manual_pages())
    errors.extend(validate_gu_families())
    errors.extend(validate_canon_gu())
    errors.extend(validate_accessories())
    errors.extend(validate_root_specs())
    errors.extend(validate_physique_specs())
    errors.extend(validate_gu_pet_content())
    errors.extend(validate_servants())
    return errors


if __name__ == "__main__":
    found = validate_all_content()
    if not found:
        print("Content validation: OK — zero errors.")
    else:
        print(f"Content validation: {len(found)} error(s):")
        for line in found:
            print(f"  - {line}")
