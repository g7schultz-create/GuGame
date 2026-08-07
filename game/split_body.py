"""
Nascent Soul Avatar — Phase 3 gives the avatar something to do outside combat: /split_body
sends it off to search for loot for a fixed real-world duration, mirroring GameManager.study's
single-pending-job shape (see manager.py's progress_split_body). This module is the data/rules
layer, same role avatar.py plays for the soul catalog -- it knows nothing about Discord or the
database, just "given a tier and an avatar level, what loot comes back."

The guaranteed bundle below is deliberately the acquisition path for Soul Nourishing Pill and
Soul Crystal (see avatar.AVATAR_LEVEL_UP_RECIPE and items.py's own comments on both items --
both explicitly named /split_body as "a later phase" for exactly this). Semi-rare equipment
(accessories/artifacts) and manual pages are NOT rolled here -- they need real grant calls
(db.create_accessory_instance, db.add_player_page), so GameManager.progress_split_body rolls
those itself, using this module only for the simple {item_name: quantity} bundle.
"""

import random
from typing import Dict, Optional

from . import avatar, items

SPLIT_BODY_DURATION_SECONDS = 3 * 60 * 60

# Tunable placeholders (same framing avatar.AVATAR_LEVEL_UP_RECIPE's own comment uses) -- base
# quantity range at avatar Level I, before avatar.AVATAR_LEVEL_MULTIPLIER scales it up to ~2.9x
# at Level X. Tier-scaled items use the player's own _player_location_rank directly (matches
# monster drop tables using realm_index+1 directly) rather than gathering.roll_tier's
# luck-weighted roll -- this is a dedicated mission tied to cultivation level, not a repeatable
# luck-driven action.
BASE_LOOT_RANGES = {
    "Primeval Essence Crystal": (10, 18),
    "Tier {tier} Herb": (4, 8),
    "Tier {tier} Beast Core": (4, 8),
    avatar.SOUL_NOURISHING_PILL: (4, 7),
    avatar.SOUL_CRYSTAL: (1, 3),
}
BASE_ESSENCE_PILL_RANGE = (1, 2)


def roll_split_body_loot(tier: int, avatar_level: int, rng: Optional[random.Random] = None) -> Dict[str, int]:
    """Returns {item_name: quantity} for a completed /split_body mission's guaranteed bundle.
    `tier` should be GameManager._player_location_rank(player) (1-7); `avatar_level` scales
    every quantity via avatar.AVATAR_LEVEL_MULTIPLIER."""
    r = rng or random
    multiplier = avatar.AVATAR_LEVEL_MULTIPLIER.get(avatar_level, 1.0)
    loot: Dict[str, int] = {}

    for name_template, (lo, hi) in BASE_LOOT_RANGES.items():
        name = name_template.format(tier=tier) if "{tier}" in name_template else name_template
        loot[name] = max(1, round(r.randint(lo, hi) * multiplier))

    essence_pill_name = items.alchemy_pill_name("Essence Restoration", tier)
    lo, hi = BASE_ESSENCE_PILL_RANGE
    loot[essence_pill_name] = max(1, round(r.randint(lo, hi) * multiplier))

    return loot
