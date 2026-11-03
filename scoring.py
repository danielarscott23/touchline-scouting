"""Transparent scoring, independent of Streamlit and source providers."""

import math
import pandas as pd
from scouting.roles import BASE_MINUTES, POSITIONS, WEIGHTS


def score_players(players: pd.DataFrame, weights=None, *, eligibility_mask=None, lower_is_better=()) -> pd.DataFrame:
    """Score one season's eligible cohort before any dashboard search filters.

    Midrank percentile = 100 * (average_rank - 0.5) / cohort_size.
    Tied values share a score; a constant metric scores 50 for everyone.
    """
    weights = WEIGHTS if weights is None else weights
    if not weights or not set(weights).issubset(players.columns):
        raise ValueError("Every weighted metric must exist in the player table.")
    if any(not math.isfinite(w) or w < 0 for w in weights.values()) or not math.isclose(sum(weights.values()), 1):
        raise ValueError("Weights must be finite, non-negative, and sum to 1.")
    if players["season"].nunique() != 1:
        raise ValueError("Choose exactly one season before scoring.")
    if not set(lower_is_better).issubset(weights):
        raise ValueError("Lower-is-better metrics must be in the role weights.")
    eligible = players["position"].isin(POSITIONS) if eligibility_mask is None else eligibility_mask.reindex(players.index, fill_value=False)
    cohort = players.loc[
        eligible & (players["minutes"] >= BASE_MINUTES)
        & players[list(weights)].notna().all(axis=1)
    ].copy()
    if cohort.empty:
        return cohort.assign(role_index=pd.Series(dtype=float), cohort_rank=pd.Series(dtype=int))
    for metric in weights:
        cohort[f"{metric}_percentile"] = 100 * (cohort[metric].rank(method="average", ascending=metric not in lower_is_better) - 0.5) / len(cohort)
        cohort[f"{metric}_contribution"] = cohort[f"{metric}_percentile"] * weights[metric]
    cohort["role_index"] = sum(cohort[f"{metric}_contribution"] for metric in weights)
    cohort["cohort_rank"] = cohort["role_index"].rank(method="min", ascending=False).astype(int)
    return cohort.sort_values(["role_index", "player_id"], ascending=[False, True]).reset_index(drop=True)


def filter_players(scored, leagues, positions, age_range, min_minutes, query="", include_unknown_age=False):
    """Filters select rows without recalculating percentiles or ranks."""
    ages = scored["age"].between(*age_range)
    if include_unknown_age:
        ages |= scored["age"].isna()
    if "position_memberships" in scored:
        selected = set(positions)
        position_matches = scored["position_memberships"].map(lambda value: bool(set(value.split("|")) & selected))
    else:
        position_matches = scored["position"].isin(positions)
    mask = (scored["league"].isin(leagues) & position_matches
            & ages & (scored["minutes"] >= min_minutes))
    if query.strip():
        mask &= (scored["name"].str.contains(query.strip(), case=False, regex=False)
                 | scored["player_id"].astype(str).str.contains(query.strip(), regex=False))
    return scored.loc[mask].copy()
