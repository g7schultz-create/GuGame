"""
/inheritance_ground's static content -- named ancient Gu Immortal inheritance sites a 3-4
player invited team explores together. Unlike everything else under search_data.py's
INHERITANCE_THEMES (which are single-player, purely pre-rolled), a ground's team works through
a shared bubble board (see GameManager.generate_inheritance_ground_board /
InheritanceGroundView's "bubble_board" phase) before the existing Final Trial + betrayal twist --
gu_rank/tags feed both the board's battle-monster scaling and the Final Trial threshold/reward
rarity, guardian_name is used in the Final Trial/betrayal flavor text.
"""

GROUNDS = {
    "blood_sea_ancestor": {
        "name": "Blood Sea Ancestor's Inheritance Ground",
        "flavor": (
            "A crimson tide once swallowed an entire sect here, and something of the "
            "Ancestor who drowned it still lingers beneath the dried lakebed."
        ),
        "gu_rank": 4,  # feeds reward rarity/rank, battle-monster pool, AND the Final Trial threshold -- tunable
        "tags": ["blood", "strength", "soul"],
        "guardian_name": "The Blood Sea Ancestor's Echo",
        # Shown on the intro embed via discord.File + attachment:// (see
        # InheritanceGroundLobbyView._resolve) -- optional; a missing/not-yet-provided file
        # just means no image gets attached, the run still works fine without one.
        "intro_image": "game/assets/inheritance_ground/blood_sea_ancestor.png",
    },
}
