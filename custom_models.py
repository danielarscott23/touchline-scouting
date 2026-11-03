"""User-selected performance metrics, independent of position presets."""
from dataclasses import dataclass
from hashlib import sha256
import json
import math

from scouting.fm_roles import position_capabilities
from scouting.scoring import score_players


@dataclass(frozen=True)
class MetricSpec:
    label: str
    group: str
    lower_is_better: bool = False
    note: str = ""


METRIC_CATALOG = {
    "xa_p90": MetricSpec("Expected assists / 90","In possession"),
    "key_passes_p90": MetricSpec("Key passes / 90","In possession"),
    "chances_created_p90": MetricSpec("Chances created / 90 (FM Ch C)","In possession",note="Retains the exported Ch C/90 field; definitions may overlap with key passes."),
    "assists_p90": MetricSpec("Assists / 90","In possession"),
    "passes_attempted_p90": MetricSpec("Passes attempted / 90","In possession"),
    "passes_completed_p90": MetricSpec("Completed passes / 90","In possession"),
    "pass_completion_pct": MetricSpec("Pass completion %","In possession"),
    "progressive_passes_p90": MetricSpec("Progressive passes / 90","In possession"),
    "dribbles_p90": MetricSpec("Dribbles / 90 (FM export)","In possession",note="Drb/90 as supplied. Attempted/completed meaning has not been established; use with care."),
    "crosses_attempted_p90": MetricSpec("Crosses attempted / 90","In possession"),
    "crosses_completed_p90": MetricSpec("Completed crosses / 90","In possession"),
    "possession_lost_p90": MetricSpec("Possession lost / 90","In possession",True,"Defaults to lower-is-better; low losses may also reflect low involvement or less risky play."),
    "tackles_attempted_p90": MetricSpec("Tackles attempted / 90","Out of possession"),
    "tackles_completed_p90": MetricSpec("Completed tackles / 90","Out of possession"),
    "interceptions_p90": MetricSpec("Interceptions / 90","Out of possession"),
    "blocks_p90": MetricSpec("Blocks / 90","Out of possession"),
    "clearances_p90": MetricSpec("Clearances / 90","Out of possession"),
    "possession_won_p90": MetricSpec("Possession won / 90","Out of possession"),
    "xg_p90": MetricSpec("xG / 90 (includes penalties)","Goal threat"),
    "goals_p90": MetricSpec("Goals / 90 (includes penalties)","Goal threat"),
    "shots_p90": MetricSpec("Shots / 90","Goal threat"),
    "shots_on_target_p90": MetricSpec("Shots on target / 90","Goal threat"),
    "aerial_attempts_p90": MetricSpec("Aerial duels attempted / 90","Aerial duels"),
    "headers_won_p90": MetricSpec("Headers won / 90","Aerial duels"),
}
GROUPS = ("In possession","Out of possession","Goal threat","Aerial duels")
DEFAULT_METRICS = ("xa_p90","key_passes_p90","progressive_passes_p90","xg_p90")


def available_metrics(players):
    return {key:spec for key,spec in METRIC_CATALOG.items() if key in players and players[key].notna().any()}


def normalise_weights(metrics,importance):
    if not metrics or len(set(metrics)) != len(metrics):
        raise ValueError("Choose at least one distinct metric.")
    if not set(metrics).issubset(METRIC_CATALOG):
        raise ValueError("Unknown performance metric.")
    raw = {metric:float(importance.get(metric,1)) for metric in metrics}
    if any(not math.isfinite(value) or value<=0 for value in raw.values()):
        raise ValueError("Each selected metric needs a positive, finite importance.")
    total = sum(raw.values())
    return {metric:value/total for metric,value in raw.items()}


def model_config(weights,lower_is_better=(),include_goalkeepers=False):
    return {"name":"Custom performance index","weights":dict(weights),
            "lower_is_better":sorted(lower_is_better),"include_goalkeepers":bool(include_goalkeepers),
            "reference_group":"All eligible players in this snapshot with at least 900 minutes and every selected metric. Sidebar filters do not redefine the reference group."}


def score_custom_model(players,weights,lower_is_better=(),include_goalkeepers=False):
    if not set(weights).issubset(METRIC_CATALOG):
        raise ValueError("Unknown performance metric.")
    config = model_config(weights,lower_is_better,include_goalkeepers)
    key = "custom_"+sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()[:12]
    capabilities = players["positions_raw"].fillna("").map(position_capabilities)
    eligible = capabilities.map(lambda values:bool(values) and (include_goalkeepers or "GK" not in values))
    scored = score_players(players,weights,eligibility_mask=eligible,lower_is_better=lower_is_better)
    scored["position_memberships"] = scored["positions_raw"].map(lambda value:"|".join(sorted(position_capabilities(value))))
    scored["role_key"] = key
    scored["role_name"] = config["name"]
    return scored
