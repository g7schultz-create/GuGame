"""
White Heaven -- an optional Dao Seeking+ endgame region, reached via a real 1-hour travel
delay each way (see /white_heaven, GameManager's white_heaven_* methods). Deliberately
separate from world_regions.py's mortal WORLD_REGIONS: that system is an instant-switch
playstyle choice capped at Nascent Soul and below; this one is a real destination with a
real journey, gated at the OTHER end of the realm ladder (Dao Seeking, great_realm_index 5,
and above -- which also covers Ancient Realm, the current top realm).

While a player's white_heaven_status is "present", /hunt, /raid, /explore, and
/search_forgotten_blessed_land all swap to White Heaven's own fixed-difficulty content (see
game/content/monsters/white_heaven.py) instead of their normal realm-based content -- see
each command's own White-Heaven branch in cog.py.
"""

from dataclasses import dataclass

WHITE_HEAVEN_MIN_GREAT_REALM_INDEX = 5  # Dao Seeking (realms.GREAT_REALMS) and above

# Real wall-clock travel delay, both directions -- confirmed via explicit request, unlike
# world_regions.py's instant switch. TESTING: shorten like every other cooldown in this
# codebase's own history if verifying end-to-end; revert to 3600 for real play.
WHITE_HEAVEN_TRAVEL_SECONDS = 3600

# Background tick cadence (see GameCog.white_heaven_tick) -- same 300s cadence every other
# auto-completing sweep in this codebase already uses (study, split_body, world boss).
WHITE_HEAVEN_TICK_INTERVAL_SECONDS = 300


def is_eligible(great_realm_index: int) -> bool:
    return great_realm_index >= WHITE_HEAVEN_MIN_GREAT_REALM_INDEX


@dataclass
class WhiteHeavenStatus:
    key: str
    label: str
    emoji: str


# The 4 states white_heaven_status cycles through: away -> traveling_there -> present ->
# traveling_back -> away.
STATUSES = {
    "away": WhiteHeavenStatus("away", "Away", "🏠"),
    "traveling_there": WhiteHeavenStatus("traveling_there", "Traveling to White Heaven", "🧳"),
    "present": WhiteHeavenStatus("present", "In White Heaven", "☁️"),
    "traveling_back": WhiteHeavenStatus("traveling_back", "Returning Home", "🧳"),
}

FLAVOR_TEXT = (
    "Beyond the reach of ordinary cultivators, White Heaven is a realm of endless cloud "
    "seas and floating continents, lit by aurora-veined skies and scarred by spatial "
    "chasms torn open by tribulations no mortal sect ever survived. Hidden grotto-heavens "
    "sealed by ancient Gu Immortals still linger here, along with the beasts and light "
    "phenomena that made this place too dangerous for anyone below Dao Seeking to ever "
    "reach in the first place."
)

# Shared image attached to /white_heaven and every White-Heaven-flavored hunt/raid/explore/
# sfbl embed while present -- same os.path.exists-guarded, graceful-degradation pattern as
# inheritance_ground_view.build_intro_image_file. File supplied later; None until then just
# means no image, never a crash.
WHITE_HEAVEN_IMAGE_PATH = "game/assets/white_heaven/white_heaven.png"
