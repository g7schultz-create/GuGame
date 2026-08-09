"""
/inheritance_ground's static content -- named ancient Gu Immortal inheritance sites a 3-4
player invited team explores together. Unlike everything else under search_data.py's
INHERITANCE_THEMES (which are single-player, purely pre-rolled, no real choice), each
GROUNDS entry's stages carry REAL branching options: which button the team picks changes the
mechanical outcome (a Trial Power delta feeding into GameManager's Final Trial check), not
just the flavor text shown.

Each option is one uniform shape so GameManager's resolution code never needs to branch on
"is this a guaranteed option or a risky one" -- success_chance=1.0 IS the guaranteed case.
"""

GROUNDS = {
    "blood_sea_ancestor": {
        "name": "Blood Sea Ancestor's Inheritance Ground",
        "flavor": (
            "A crimson tide once swallowed an entire sect here, and something of the "
            "Ancestor who drowned it still lingers beneath the dried lakebed."
        ),
        "gu_rank": 4,  # feeds reward rarity/rank AND the Final Trial threshold -- tunable
        "tags": ["blood", "strength", "soul"],
        "guardian_name": "The Blood Sea Ancestor's Echo",
        "stages": [
            {
                "id": "poisoned_array",
                "title": "The Poisoned Array",
                "prompt": (
                    "The entrance is sealed behind a still-active poison array, its lattice "
                    "humming red. Someone has to decide how the team gets through."
                ),
                "options": [
                    {
                        "id": "sacrifice_stones", "label": "Sacrifice Primeval Stones", "emoji": "💎",
                        "description": "Burn essence to neutralize it cleanly. Costs every member 50 spirit stones.",
                        "stone_cost_per_member": 50, "success_chance": 1.0, "success_power_delta": 0,
                        "success_flavor": "The array's red lattice dims and folds away, paid off in full.",
                        "failure_power_delta": 0, "failure_flavor": "",
                    },
                    {
                        "id": "brute_force", "label": "Brute Force", "emoji": "💥",
                        "description": "Push straight through. Free, but the backlash might cost the team.",
                        "stone_cost_per_member": 0, "success_chance": 0.65, "success_power_delta": 5,
                        "success_flavor": "The array shatters under raw pressure — barely a scratch, and morale surges.",
                        "failure_power_delta": -15,
                        "failure_flavor": "The poison bites back before it breaks — the whole team staggers in, wounded.",
                    },
                    {
                        "id": "send_ahead", "label": "Send a Squad Member Ahead", "emoji": "🏃",
                        "description": "One volunteer tests it first. Safer for the group, riskier for them.",
                        "stone_cost_per_member": 0, "success_chance": 0.8, "success_power_delta": 0,
                        "success_flavor": "{volunteer} finds the safe seam in the lattice and waves the rest through.",
                        "failure_power_delta": -10,
                        "failure_flavor": "{volunteer} takes the array's full backlash alone, staggering but upright.",
                    },
                ],
            },
            {
                "id": "bone_corridor",
                "title": "The Bone Corridor",
                "prompt": (
                    "Deeper in, a corridor floored in bleached bone narrows toward a single "
                    "sealed door. The Ancestor's will still presses against anyone who enters."
                ),
                "options": [
                    {
                        "id": "recite_oath", "label": "Recite the Ancestor's Oath", "emoji": "📜",
                        "description": "Speak the old blood-oath from memory. Free, and the wiser choice usually pays off.",
                        "stone_cost_per_member": 0, "success_chance": 0.7, "success_power_delta": 10,
                        "success_flavor": "The corridor recognizes the old words — the bone floor stills, and the way opens with ease.",
                        "failure_power_delta": 0,
                        "failure_flavor": "Half-remembered words earn no favor, but no punishment either — the door simply opens.",
                    },
                    {
                        "id": "force_seal", "label": "Force the Seal", "emoji": "🗝️",
                        "description": "Pay the door directly. Costs every member 75 spirit stones, guaranteed clean passage.",
                        "stone_cost_per_member": 75, "success_chance": 1.0, "success_power_delta": 5,
                        "success_flavor": "The seal accepts the toll without protest, and the corridor's pressure lifts entirely.",
                        "failure_power_delta": 0, "failure_flavor": "",
                    },
                    {
                        "id": "blood_sea_judgment", "label": "Let the Blood Sea Judge You", "emoji": "🩸",
                        "description": "Offer no toll, no words — just walk in and let the Ancestor decide. High risk, high reward.",
                        "stone_cost_per_member": 0, "success_chance": 0.5, "success_power_delta": 20,
                        "success_flavor": "The Blood Sea finds the team worthy — its favor surges through every member.",
                        "failure_power_delta": -20,
                        "failure_flavor": "The Blood Sea finds the team wanting, and its judgment is not gentle.",
                    },
                ],
            },
        ],
    },
}
