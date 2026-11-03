"""Find comparable statistical profiles inside one fixed role cohort."""
import math
import pandas as pd


def find_similar_players(scored, reference_id, weights, candidate_ids=None, limit=10):
    """100 minus weighted RMS percentile distance; not a probability.

    All inputs must come from the same model/season cohort. Filters restrict
    candidates only: they never recompute the reference group's percentiles.
    The reference player is always excluded, including when profiles tie.
    """
    if not weights or any(not math.isfinite(w) or w < 0 for w in weights.values()) or not math.isclose(sum(weights.values()), 1):
        raise ValueError("Similarity weights must be finite, non-negative and sum to 1.")
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("Limit must be a positive integer.")
    if scored["player_id"].astype(str).duplicated().any():
        raise ValueError("Similarity requires one row per player in a single role cohort.")
    for column in ("season", "role_key"):
        if column in scored and scored[column].nunique() > 1:
            raise ValueError("Use a single role and season for similarity.")
    columns = [f"{metric}_percentile" for metric in weights]
    if not set(columns).issubset(scored.columns):
        raise ValueError("Missing role percentiles; score the cohort first.")
    percentiles = scored[columns]
    if percentiles.isna().any().any() or not percentiles.apply(lambda values: values.between(0, 100).all()).all():
        raise ValueError("Role percentiles must be finite numbers between 0 and 100.")
    target = scored.loc[scored["player_id"].astype(str).eq(str(reference_id))]
    if len(target) != 1:
        raise ValueError("The reference player must belong to the selected role cohort.")
    candidates = scored.loc[~scored["player_id"].astype(str).eq(str(reference_id))].copy()
    if candidate_ids is not None:
        allowed = {str(pid) for pid in candidate_ids}
        candidates = candidates.loc[candidates["player_id"].astype(str).isin(allowed)].copy()
    metric_weights = pd.Series({f"{metric}_percentile": weight for metric, weight in weights.items()})
    squared_gaps = candidates[columns].sub(target.iloc[0][columns]).pow(2)
    candidates["profile_distance"] = squared_gaps.mul(metric_weights).sum(axis=1).pow(.5).astype(float)
    candidates["profile_similarity"] = (100 - candidates["profile_distance"]).clip(0,100)
    candidates["reference_player_id"] = str(reference_id)
    candidates = candidates.sort_values(["profile_distance", "player_id"], kind="stable").head(limit).reset_index(drop=True)
    candidates.insert(0, "similarity_rank", range(1,len(candidates)+1))
    return candidates


def metric_gaps(reference, candidate, weights, labels):
    """Explain each match with signed raw differences and percentile gaps."""
    return pd.DataFrame([
        {"Metric": labels[metric], "Reference": reference[metric], "Match": candidate[metric],
         "Raw difference": candidate[metric] - reference[metric],
         "Reference percentile": reference[f"{metric}_percentile"],
         "Match percentile": candidate[f"{metric}_percentile"],
         "Percentile gap": abs(candidate[f"{metric}_percentile"] - reference[f"{metric}_percentile"])}
        for metric in weights
    ])
