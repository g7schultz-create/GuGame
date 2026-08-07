"""
Semi-random manual generation (design doc section 7). Everything here is deterministic given
a seed — the same (source, rank, rarity, theme_tags, seed) always reconstructs the identical
manual, so a manual only needs its seed + component page ids stored, not a frozen snapshot.

Effect math follows the doc's own explicit warning: never sum raw page percentages directly.
Instead, page power_value is summed into a single budget, capped by rank, scaled by rarity
efficiency and coherence, and only THEN converted into the manual's actual effect numbers —
see resolve_manual_effects.
"""

import random
import time
from typing import Dict, List, Optional

from . import manual_data
from .manual_data import (
    FLAW_SEVERITY_BUDGET,
    FLAWS,
    MANUAL_RANK_TABLE,
    NAME_CORE_IMAGES,
    NAME_METHOD_WORDS,
    NAME_PREFIXES,
    OPTIONAL_CATEGORIES,
    PAGES,
    RARITY_DEFECT_CHANCE,
    RARITY_EFFICIENCY,
    RARITY_HIDDEN_EFFECT_CHANCE,
    ManualPage,
    _coherence_band,
)

MAX_GENERATION_ATTEMPTS = 40  # safety valve against an unlucky/impossible fill loop


def weighted_path_choice(theme_tags: List[str], rng: random.Random) -> str:
    """Picks a primary path tag, favoring whatever the source's theme already leans toward."""
    if theme_tags:
        return rng.choice(theme_tags)
    return rng.choice(manual_data.ALL_PATH_TAGS)


def roll_page_slots(rank: int, rarity: str, rng: random.Random) -> int:
    lo, hi = MANUAL_RANK_TABLE[rank].page_slots
    slots = rng.randint(lo, hi)
    # Higher rarity nudges toward the top of the range (more complete manuals), matching the
    # rarity table's "fewer dead pages" framing for Rare+ without hard-guaranteeing max slots.
    if rarity in ("Epic", "Legendary", "Mythic", "Divine", "Unique") and slots < hi:
        slots += 1
    return min(hi, slots)


def _candidates_for(category: str, rank: int, primary_path: str, theme_tags: List[str]) -> List[ManualPage]:
    pool = [p for p in PAGES.values() if p.category == category and p.rank <= rank + 1]
    if not pool:
        return []
    tag_set = set(theme_tags) | {primary_path}
    matching = [p for p in pool if tag_set & set(p.tags)]
    return matching or pool


def select_page(category: str, rank: int, primary_path: str, theme_tags: List[str], rng: random.Random) -> Optional[ManualPage]:
    candidates = _candidates_for(category, rank, primary_path, theme_tags)
    if not candidates:
        return None
    # Prefer pages at-or-below the manual's own rank; only reach a rank above it if nothing
    # else fits (see is_valid_addition for the coherence/instability cost of doing so).
    same_or_lower = [p for p in candidates if p.rank <= rank]
    pool = same_or_lower or candidates
    return rng.choice(pool)


def is_valid_addition(candidate: Optional[ManualPage], pages: List[ManualPage], rank: int) -> bool:
    if candidate is None or candidate.page_id in {p.page_id for p in pages}:
        return False
    if candidate.rank > rank + 1:
        return False  # two or more ranks above the manual — normally invalid, per the coherence table
    return True


def calculate_coherence(pages: List[ManualPage], primary_path: str, bonus_tags: Dict[str, int] = None,
                         bonus_categories: Dict[str, int] = None, flat_bonus: int = 0) -> int:
    """bonus_tags/bonus_categories are a root's own preview-coherence resonance (see
    character_data.CharacterTraitSpec) — summed per matching page, then capped at
    character_data.MANUAL_COHERENCE_BONUS_CAP so one root can't blow past the design brief's
    own coherence budget (section 4.1) no matter how many matching pages a manual happens to
    have. flat_bonus is that same root's manual_coherence_flat — applies once, regardless of
    any page's tags/category, still folded into the same capped total. Preview-only, exactly
    like the rest of this function's score: it shifts which coherence BAND a manual lands in,
    not the underlying page math."""
    score = 0
    root_bonus = flat_bonus
    for page in pages:
        root_bonus += sum(bonus_tags.get(tag, 0) for tag in page.tags) if bonus_tags else 0
        root_bonus += (bonus_categories or {}).get(page.category, 0)
    if root_bonus:
        from .character_data import MANUAL_COHERENCE_BONUS_CAP
        root_bonus = min(MANUAL_COHERENCE_BONUS_CAP, root_bonus)
    tag_counts: Dict[str, int] = {}
    for page in pages:
        for tag in page.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    foundation = next((p for p in pages if p.category == "Foundation"), None)
    circulation = next((p for p in pages if p.category == "Circulation"), None)
    breakthrough = next((p for p in pages if p.category == "Breakthrough"), None)

    for page in pages:
        if primary_path in page.tags:
            score += 10
        if any(tag_counts.get(tag, 0) >= 3 for tag in page.tags):  # shares with >=2 OTHER pages
            score += 4

    if foundation and circulation and set(foundation.tags) & set(circulation.tags):
        score += 8
    if breakthrough and primary_path in breakthrough.tags:
        score += 8

    present_categories = {p.category for p in pages}
    if {"Foundation", "Circulation"} <= present_categories:
        score += 10

    manual_rank = max((p.rank for p in pages), default=1)
    over_rank = sum(1 for p in pages if p.rank == manual_rank + 1)
    score -= 8 * over_rank

    for page in pages:
        if page.category == "Restriction":
            score += 5  # a Restriction page is only ever added deliberately in this generator, so it always "supports the theme"

    score += root_bonus
    return max(0, min(100, score))


def resolve_manual_effects(pages: List[ManualPage], rank: int, rarity: str, coherence: int, comprehension: int = 0,
                            effectiveness_mult: float = 1.0) -> dict:
    band = _coherence_band(coherence)
    rank_cap = MANUAL_RANK_TABLE[rank].power_budget
    raw_power = sum(page.power_value for page in pages)
    usable_power = min(raw_power, rank_cap)
    scale = (usable_power / raw_power) if raw_power > 0 else 0.0

    effective_multiplier = RARITY_EFFICIENCY[rarity] * band.power_multiplier * (1 + comprehension / 500) * effectiveness_mult
    effects: Dict[str, float] = {}
    for page in pages:
        for key, value in page.base_effects.items():
            effects[key] = effects.get(key, 0.0) + value * scale * effective_multiplier
    return {key: round(value, 2) for key, value in effects.items()}


def refinement_bonus_totals(pages: List[ManualPage], owned: Dict[str, dict]) -> dict:
    """How much /assemble_manual should reward the refinement level of the specific page
    copies being spent (see manual_data.REFINEMENT_SPEC). effectiveness_mult is power_value
    -weighted across the pages used, so a single Perfected Foundation page still pulls real
    weight even if everything else in the build is Unstudied, rather than being diluted to a
    flat per-page average. stability_bonus sums (more refined pages built a sturdier manual).
    flaw_repair_chance takes the single best page's chance rather than stacking every page's
    own (one well-warded page catching a defect is the intended fantasy, not multiplicative
    chances from unrelated pages). owned is GameDatabase.get_player_pages' shape."""
    specs = [
        manual_data.REFINEMENT_SPEC.get(
            owned.get(page.page_id, {}).get("refinement_level", "Unstudied"), manual_data.REFINEMENT_SPEC["Unstudied"]
        )
        for page in pages
    ]
    total_power = sum(page.power_value for page in pages) or 1
    effectiveness_mult = 1.0 + sum(
        spec.effectiveness_bonus_pct * page.power_value for page, spec in zip(pages, specs)
    ) / total_power
    stability_bonus = sum(spec.stability_bonus for spec in specs)
    flaw_repair_chance = max((spec.flaw_repair_chance for spec in specs), default=0.0)
    return {
        "effectiveness_mult": effectiveness_mult,
        "stability_bonus": stability_bonus,
        "flaw_repair_chance": flaw_repair_chance,
    }


def roll_flaws(pages: List[ManualPage], rarity: str, coherence: int, rng: random.Random) -> List[str]:
    flaw_ids: List[str] = []
    pool = list({fid for page in pages for fid in page.flaw_pool})
    if pool and rng.random() < RARITY_DEFECT_CHANCE[rarity]:
        flaw_ids.append(rng.choice(pool))
    # Very low coherence can introduce an "incoherent" flaw even with no page-sourced pool,
    # reflecting a genuinely mismatched build rather than any single page's own defect.
    if coherence < 30 and rng.random() < 0.5 and "oath_upkeep" not in flaw_ids:
        candidate = rng.choice(list(FLAWS.keys()))
        if candidate not in flaw_ids:
            flaw_ids.append(candidate)
    return flaw_ids


def generate_manual_name(primary_path: str, pages: List[ManualPage], source: str, rng: random.Random) -> str:
    prefix = rng.choice(NAME_PREFIXES)
    core = rng.choice(NAME_CORE_IMAGES)
    method = rng.choice(NAME_METHOD_WORDS)
    return f"{prefix} {core} {method}"


def generate_manual(source: str, rank: int, rarity: str, theme_tags: List[str], complete: bool = True, seed: Optional[int] = None) -> dict:
    """Returns a plain dict ready for GameDatabase.create_manual — see that method's shape.
    Deterministic: the same (source, rank, rarity, theme_tags, seed) always reconstructs the
    exact same manual, so only the seed + inputs need to be stored, not a frozen snapshot."""
    if seed is None:
        seed = random.randrange(1, 2**31)
    rng = random.Random(seed)

    primary_path = weighted_path_choice(theme_tags, rng)
    slots = roll_page_slots(rank, rarity, rng)

    pages: List[ManualPage] = []
    foundation = select_page("Foundation", rank, primary_path, theme_tags, rng)
    if foundation:
        pages.append(foundation)
    circulation = select_page("Circulation", rank, primary_path, theme_tags, rng)
    if circulation and circulation.page_id not in {p.page_id for p in pages}:
        pages.append(circulation)

    if complete:
        breakthrough = select_page("Breakthrough", rank, primary_path, theme_tags, rng)
        if breakthrough and is_valid_addition(breakthrough, pages, rank):
            pages.append(breakthrough)

    attempts = 0
    while len(pages) < slots and attempts < MAX_GENERATION_ATTEMPTS:
        attempts += 1
        category = rng.choice(OPTIONAL_CATEGORIES)
        candidate = select_page(category, rank, primary_path, theme_tags, rng)
        if is_valid_addition(candidate, pages, rank):
            pages.append(candidate)

    coherence = calculate_coherence(pages, primary_path)
    band = _coherence_band(coherence)
    effects = resolve_manual_effects(pages, rank, rarity, coherence)
    flaw_ids = roll_flaws(pages, rarity, coherence, rng)
    name = generate_manual_name(primary_path, pages, source, rng)

    secondary_paths = sorted({tag for page in pages for tag in page.tags if tag != primary_path})[:5]
    # band.deviation_modifier can itself be negative (Harmonious+ bands reduce risk), which
    # would push this over 100 without the upper clamp too.
    stability = max(0, min(100, 100 - band.deviation_modifier - 8 * len(flaw_ids)))

    return {
        "name": name,
        "rank": rank,
        "rarity": rarity,
        "primary_path": primary_path,
        "secondary_paths": secondary_paths,
        "page_ids": [p.page_id for p in pages],
        "coherence": coherence,
        "coherence_band": band.label,
        "stability": stability,
        "comprehension": 0,
        "effects": effects,
        "flaws": flaw_ids,
        "generation_seed": seed,
        "bound": False,
    }


def reroll_effects_for_comprehension(manual_row: dict) -> dict:
    """Recomputes effects with the manual's current comprehension applied — call after
    GameDatabase.set_manual_comprehension so /manual inspect reflects the boost immediately
    without needing a full regeneration."""
    pages = [PAGES[pid] for pid in manual_row["page_ids"] if pid in PAGES]
    return resolve_manual_effects(
        pages, manual_row["rank"], manual_row["rarity"], manual_row["coherence"], manual_row["comprehension"],
        manual_row.get("refinement_effect_mult", 1.0),
    )
