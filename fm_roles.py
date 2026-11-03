"""Explicit, provisional position models based only on exported performance.

Position eligibility uses FM's listed capabilities, not attributes or observed
position-specific minutes. These models are hypotheses, not validated ratings.
"""
from dataclasses import dataclass
from functools import lru_cache
import re

from scouting.fm24 import FM_WEIGHTS, FM_LABELS
from scouting.scoring import score_players


@dataclass(frozen=True)
class RoleProfile:
    name: str
    positions: tuple[str, ...]
    weights: dict[str, float]
    note: str
    lower_is_better: tuple[str, ...] = ()


METRIC_LABELS = {
    **FM_LABELS,
    "interceptions_p90": "Interceptions / 90",
    "headers_won_p90": "Headers won / 90",
    "tackles_completed_p90": "Completed tackles / 90",
    "pass_completion_pct": "Pass completion %",
    "possession_lost_p90": "Possession lost / 90",
    "possession_won_p90": "Possession won / 90",
    "crosses_completed_p90": "Completed crosses / 90",
    "shots_on_target_p90": "Shots on target / 90",
    "goals_p90": "Goals / 90 (includes penalties)",
    "passes_completed_p90": "Completed passes / 90",
}

ROLE_PROFILES = {
    "creative": RoleProfile("Creative midfielder — broad pool", ("AM", "CM", "LM", "RM", "LW", "RW"),
        FM_WEIGHTS, "Original broad candidate pool; emphasises chance creation and passing progression."),
    "centre_back": RoleProfile("Centre-back", ("CB",),
        {"interceptions_p90": .25, "headers_won_p90": .25, "tackles_completed_p90": .15,
         "pass_completion_pct": .15, "progressive_passes_p90": .20},
        "Balances defensive actions, aerial involvement and passing. Action volumes depend on team style and opportunity."),
    "full_back": RoleProfile("Full-back", ("LB", "RB"),
        {"interceptions_p90": .20, "tackles_completed_p90": .20, "progressive_passes_p90": .25,
         "xa_p90": .20, "pass_completion_pct": .15},
        "Balances defensive activity, progression and chance creation. Select LB or RB below to filter by side."),
    "wing_back": RoleProfile("Wing-back", ("LWB", "RWB"),
        {"progressive_passes_p90": .25, "crosses_completed_p90": .25, "xa_p90": .25,
         "possession_won_p90": .15, "pass_completion_pct": .10},
        "Emphasises progression, crossing and chance creation while retaining a ball-recovery contribution."),
    "defensive_midfielder": RoleProfile("Defensive midfielder", ("DM",),
        {"interceptions_p90": .25, "tackles_completed_p90": .20, "progressive_passes_p90": .25,
         "pass_completion_pct": .20, "possession_lost_p90": .10},
        "Balances ball winning, progression and retention. Fewer losses can also reflect lower-risk or lower-volume play.",
        ("possession_lost_p90",)),
    "central_midfielder": RoleProfile("Central midfielder", ("CM",),
        {"progressive_passes_p90": .30, "xa_p90": .20, "key_passes_p90": .15,
         "pass_completion_pct": .20, "possession_lost_p90": .15},
        "A passing-focused central-midfield model. Passing and retention metrics partly overlap.",
        ("possession_lost_p90",)),
    "attacking_midfielder": RoleProfile("Attacking midfielder", ("AM",),
        {"xa_p90": .35, "key_passes_p90": .30, "progressive_passes_p90": .20, "xg_p90": .15},
        "A narrower central attacking-midfielder pool, weighted towards chance creation."),
    "winger": RoleProfile("Winger / wide midfielder", ("LW", "RW", "LM", "RM"),
        {"xa_p90": .30, "key_passes_p90": .15, "xg_p90": .25,
         "shots_on_target_p90": .15, "crosses_completed_p90": .15},
        "Measures wide chance creation and goal threat. Dribbling and carrying are omitted because their required definitions/data are unavailable."),
    "striker": RoleProfile("Striker", ("ST",),
        {"xg_p90": .45, "shots_on_target_p90": .25, "xa_p90": .15, "goals_p90": .15},
        "Emphasises chance quality, shooting and scoring with a smaller creation contribution. Goals and xG overlap; both include penalties."),
    "goalkeeper": RoleProfile("Goalkeeper — distribution only", ("GK",),
        {"pass_completion_pct": .60, "passes_completed_p90": .40},
        "DISTRIBUTION ONLY: this export lacks saves, goals conceded and post-shot xG. This is not an overall goalkeeper or shot-stopping rating. Short-pass tactics can inflate this score."),
}

POSITION_LABELS = {
    "GK": "Goalkeeper", "CB": "Centre-back", "LB": "Left-back", "RB": "Right-back",
    "LWB": "Left wing-back", "RWB": "Right wing-back", "DM": "Defensive midfield",
    "CM": "Central midfield", "AM": "Central attacking midfield", "LM": "Left midfield",
    "RM": "Right midfield", "LW": "Left wing", "RW": "Right wing", "ST": "Striker",
}


@lru_cache(maxsize=1024)
def position_capabilities(value: str) -> frozenset[str]:
    """Preserve every listed position, including combined forms D/WB/M/AM (L)."""
    groups = set()
    for matched in re.finditer(r"([A-Z]+(?:/[A-Z]+)*)\s*(?:\(([RLC]+)\))?", value):
        roles, sides = matched[1].split("/"), matched[2] or ""
        for role in roles:
            if role in ("GK", "DM", "ST"):
                groups.add(role)
            elif role == "D":
                groups.update(code for side, code in (("C", "CB"), ("L", "LB"), ("R", "RB")) if side in sides)
            elif role == "WB":
                groups.update(code for side, code in (("L", "LWB"), ("R", "RWB")) if side in sides)
            elif role == "M":
                groups.update(code for side, code in (("C", "CM"), ("L", "LM"), ("R", "RM")) if side in sides)
            elif role == "AM":
                groups.update(code for side, code in (("C", "AM"), ("L", "LW"), ("R", "RW")) if side in sides)
    return frozenset(groups)


def role_candidates(players, role_key):
    profile = ROLE_PROFILES[role_key]
    allowed = set(profile.positions)
    return players["positions_raw"].fillna("").map(lambda value: bool(position_capabilities(value) & allowed))


def score_fm_role(players, role_key):
    profile = ROLE_PROFILES[role_key]
    scored = score_players(players, profile.weights, eligibility_mask=role_candidates(players, role_key),
                           lower_is_better=profile.lower_is_better)
    allowed = set(profile.positions)
    scored["position_memberships"] = scored["positions_raw"].map(
        lambda value: "|".join(sorted(position_capabilities(value) & allowed)))
    scored["role_key"] = role_key
    scored["role_name"] = profile.name
    return scored
