"""
Black Heaven -- a second, deadlier Dao Seeking+ endgame region alongside White Heaven, reached
via a real 2-hour travel delay each way (double White Heaven's own 1h -- see /black_heaven,
GameManager's black_heaven_* methods). Same eligibility floor as White Heaven (great_realm_index
5 and above), but a completely different content shape: /hunt and /raid behave normally even
while present here -- the entire region is built around one minigame, /search_black_heaven (see
game/black_heaven_search_view.py), an invite-based 20-bubble board where some bubbles hide one
of 15 new Rank 7/8 Unique Gu, others are guarded by very dangerous monsters, and the rest hold
essence crystals/pills/Rank 8 materials/nothing -- every bubble's real contents are revealed once
the team's pops run out, whether they got there or not.

white_heaven_status and black_heaven_status are fully independent player columns with no
mutual-exclusivity check -- a character could in principle be "present" in both at once,
mirroring how world_region and white_heaven_status already coexist as separate location flags.
"""

from dataclasses import dataclass

BLACK_HEAVEN_MIN_GREAT_REALM_INDEX = 5  # Dao Seeking (realms.GREAT_REALMS) and above -- same gate as White Heaven

# Real wall-clock travel delay, both directions -- 2h, double White Heaven's own 1h, per
# explicit request ("very dangerous" / more remote). TESTING: shorten like every other cooldown
# in this codebase's own history if verifying end-to-end; revert to 7200 for real play.
BLACK_HEAVEN_TRAVEL_SECONDS = 2 * 3600

# Background tick cadence (see GameCog.black_heaven_tick) -- same 300s cadence every other
# auto-completing sweep in this codebase already uses (study, split_body, world boss, White Heaven).
BLACK_HEAVEN_TICK_INTERVAL_SECONDS = 300


def is_eligible(great_realm_index: int) -> bool:
    return great_realm_index >= BLACK_HEAVEN_MIN_GREAT_REALM_INDEX


@dataclass
class BlackHeavenStatus:
    key: str
    label: str
    emoji: str


# The 4 states black_heaven_status cycles through: away -> traveling_there -> present ->
# traveling_back -> away.
STATUSES = {
    "away": BlackHeavenStatus("away", "Away", "🏠"),
    "traveling_there": BlackHeavenStatus("traveling_there", "Traveling to Black Heaven", "🌑"),
    "present": BlackHeavenStatus("present", "In Black Heaven", "☠️"),
    "traveling_back": BlackHeavenStatus("traveling_back", "Returning Home", "🌑"),
}

FLAVOR_TEXT = (
    "There is no sky in Black Heaven, only a starless dark that swallows sound along with "
    "light. Nothing grows here, nothing heals here, and nothing that calls it home is weak "
    "enough to have been driven out by something worse. Cultivators who return from it tell "
    "of treasures no other realm holds — and of the ones who went in with them and didn't "
    "come back to tell anything at all."
)

# Shared image attached to /black_heaven and /search_black_heaven while present -- same
# os.path.exists-guarded, graceful-degradation pattern as white_heaven.WHITE_HEAVEN_IMAGE_PATH.
# File supplied later; None until then just means no image, never a crash.
BLACK_HEAVEN_IMAGE_PATH = "game/assets/black_heaven/black_heaven.png"
