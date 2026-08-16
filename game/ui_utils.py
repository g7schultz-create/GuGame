import random

import discord

BAR_LENGTH = 12
FILLED_CHAR = "█"
EMPTY_CHAR = "░"

NAV_PREV_VALUE = "__prev_page__"
NAV_NEXT_VALUE = "__next_page__"


def paginate_select_options(options: list, page: int, reserved_slots: int = 0) -> tuple:
    """Slices a full SelectOption list down to Discord's 25-per-select cap. If it already
    fits, returns it untouched (single page, no nav entries). Otherwise chunks it into pages
    and tacks on '<- Previous Page' / 'Next Page ->' pseudo-options at the edges as needed,
    leaving room for both within the cap. `reserved_slots` further shrinks the per-page
    budget for options the CALLER adds outside this pagination (e.g. a leading "Unequip"
    entry) so the final assembled list still never exceeds 25. Returns
    (page_options, total_pages, clamped_page)."""
    budget = 25 - reserved_slots
    if len(options) <= budget:
        return options, 1, 0
    page_size = budget - 2  # room for both nav entries on a middle page
    total_pages = (len(options) + page_size - 1) // page_size
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    chunk = list(options[start:start + page_size])
    if page > 0:
        chunk.insert(0, discord.SelectOption(label="◀ Previous Page", value=NAV_PREV_VALUE))
    if page < total_pages - 1:
        chunk.append(discord.SelectOption(label="Next Page ▶", value=NAV_NEXT_VALUE))
    return chunk, total_pages, page


def add_shuffled(view: discord.ui.View, buttons: list) -> None:
    """Adds every already-constructed discord.ui.Button in `buttons` to `view` in a RANDOMIZED
    order -- anti-macro measure for combat views (hunt/raid/battlefield/pvp/Inheritance
    Ground): a click-macro that always taps the same fixed screen position ("wherever Attack
    used to be") no longer reliably lands on the same action every round, since Attack/Guard/
    Empower/etc. reshuffle their on-screen position each render. A real player reads the
    label/emoji either way, so this costs legitimate play nothing. Each button's own `row` is
    whatever was already set at construction time and is untouched here -- discord.py lays out
    same-row items left-to-right in the order they're added to the view, which is the ONLY
    thing this function actually randomizes; overall row layout (e.g. a target Select kept on
    its own row) is unaffected."""
    shuffled = list(buttons)
    random.shuffle(shuffled)
    for button in shuffled:
        view.add_item(button)


def render_bar(current: float, maximum: float, length: int = BAR_LENGTH) -> str:
    maximum = max(1, maximum)
    filled = round(length * max(0.0, min(1.0, current / maximum)))
    return FILLED_CHAR * filled + EMPTY_CHAR * (length - filled)


def format_duration(seconds: float) -> str:
    """Compact human-readable duration, e.g. '2d 5h', '3h 12m', '45s'."""
    seconds = max(0, int(round(seconds)))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)

    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


NUMBER_SHORTHAND_THRESHOLD = 100_000_000
NUMBER_SHORTHAND_SUFFIXES = ((10**12, "T"), (10**9, "B"), (10**6, "M"))


def format_number(value, decimals: int = 2) -> str:
    """Comma-formatted below 100,000,000 -- identical to every existing `:,`-style display
    (ints stay plain, floats keep `decimals` digits, defaulting to 2 to match the codebase's
    most common float display). At and above 100M, collapses to K/M/B/T shorthand (always 2
    decimal places) instead of a wall of digits -- late-game numbers already reach into the
    hundreds of billions (Ancient Realm's own qi requirements, see realms.py; the top realm's
    qi keeps banking uncapped past Peak on top of that), so this is the single shared place
    every large-number display should route through rather than each call site inventing its
    own cutoff."""
    if value < 0:
        return f"-{format_number(-value, decimals)}"
    if value < NUMBER_SHORTHAND_THRESHOLD:
        return f"{value:,.{decimals}f}" if isinstance(value, float) else f"{value:,}"
    for threshold, suffix in NUMBER_SHORTHAND_SUFFIXES:
        if value >= threshold:
            return f"{value / threshold:,.2f}{suffix}"
    return f"{value:,}"


PATH_EMOJI = {"Righteous": "☯️", "Demonic": "👹", "Rogue": "🗡️"}


def path_footer(player) -> str:
    # player is normally a sqlite3.Row (supports [] but not .get()), so index directly —
    # cultivation_path is always a real column, just possibly NULL pre-/join.
    path = player["cultivation_path"]
    return f"{PATH_EMOJI.get(path, '🌀')} {path or 'Unaligned'} Cultivator"
