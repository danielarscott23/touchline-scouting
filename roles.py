"""Role definitions live here so the UI and scoring use the same settings."""

ROLE_NAME = "Creative attacking midfielder"
POSITIONS = ("AM", "CM", "LW", "RW")
BASE_MINUTES = 900

# These are illustrative design choices, not Barcelona's actual model.
# All six metrics are higher-is-better in this first version.
WEIGHTS = {
    "xa_p90": 0.25,
    "key_passes_p90": 0.20,
    "progressive_passes_p90": 0.20,
    "progressive_carries_p90": 0.15,
    "npxg_p90": 0.10,
    "box_receptions_p90": 0.10,
}
LABELS = {
    "xa_p90": "Expected assists / 90",
    "key_passes_p90": "Key passes / 90",
    "progressive_passes_p90": "Progressive passes / 90",
    "progressive_carries_p90": "Progressive carries / 90",
    "npxg_p90": "Non-penalty xG / 90",
    "box_receptions_p90": "Box receptions / 90",
}
