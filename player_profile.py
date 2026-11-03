"""Dedicated player record view, using every field from the active snapshot."""
import pandas as pd
import streamlit as st
from html import escape

from scouting.custom_models import METRIC_CATALOG,GROUPS
from scouting.views import player_name
from scouting.percentiles import display_percentile

FIELD_LABELS = {
    "minutes":"Minutes", "appearances_raw":"Appearances as exported (starts + substitutes)",
    "starts":"Starts", "sub_appearances":"Substitute appearances", "appearances":"Total appearances",
    "goals":"Goals (includes penalties)", "penalty_goals":"Penalty goals", "assists":"Assists",
    "tackles_attempted":"Tackles attempted", "tackles_completed":"Completed tackles",
    "penalty_goals_p90":"Penalty goals / 90",
}


def field_label(field):
    if field in METRIC_CATALOG:
        return METRIC_CATALOG[field].label
    return FIELD_LABELS.get(field,field.replace("_"," ").capitalize())


def field_value(value):
    if pd.isna(value):
        return "—"
    if isinstance(value,(float,int)) and not isinstance(value,bool):
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return str(value)


def profile_percentiles(row,benchmark,fields,lower_is_better=()):
    """Rank recorded stats within the fixed, unfiltered model benchmark.

    Missing values are excluded separately for each extra statistic. Players
    outside the benchmark receive no percentile rather than an invented rank.
    """
    result = {}
    indexed = benchmark.set_index("player_id")
    for field in fields:
        if field not in indexed or row["player_id"] not in indexed.index:
            result[field] = None
            continue
        values = pd.to_numeric(indexed[field],errors="coerce").dropna()
        if row["player_id"] not in values.index or values.empty:
            result[field] = None
            continue
        ranks = values.rank(method="average",ascending=field not in lower_is_better)
        result[field] = 100*(ranks.loc[row["player_id"]]-.5)/len(values)
    return result


def profile_stats_html(row,fields,percentiles,weights=None):
    """Use the same ticked percentile scales as player cards, in both themes."""
    rows = []
    for field in fields:
        percentile = percentiles.get(field)
        label = escape(field_label(field))
        if weights is not None:
            label += f'<small>{weights[field]*100:.1f}% weight</small>'
        if percentile is None:
            bar = '<span class="profile-no-percentile">—</span>'
        else:
            display = display_percentile(percentile)
            width = max(0,min(100,float(percentile)))
            tone = "strong" if percentile>=75 else "steady" if percentile>=50 else "muted"
            bar = (f'<div class="profile-percentile" aria-label="Percentile {display:.2f}">'
                   f'<span>{display:.2f} pctl</span><div class="stat-track">'
                   f'<div class="stat-fill {tone}" style="width:{width:.4f}%"></div></div></div>')
        rows.append(f'<div class="profile-stat-row"><div class="profile-stat-label">{label}</div>'
                    f'<div class="profile-stat-value">{escape(field_value(row[field]))}</div>{bar}</div>')
    return ('<div class="profile-stats"><div class="profile-stat-row profile-stat-heading">'
            '<div>Statistic</div><div>Value</div><div>Percentile</div></div>'+"".join(rows)+'</div>')


def render_player_profile(row,scored_row,weights,provenance,show_table,on_back,benchmark,lower_is_better=()):
    fields_with_percentiles = set(METRIC_CATALOG)|set(FIELD_LABELS)|set(weights)
    directions = {field for field,spec in METRIC_CATALOG.items() if spec.lower_is_better}
    # Selected metrics use the user's direction, including explicit overrides.
    directions.difference_update(weights)
    directions.update(lower_is_better)
    percentiles = profile_percentiles(row,benchmark,fields_with_percentiles,directions)
    def stat_table(fields):
        st.html(profile_stats_html(row,fields,percentiles))

    st.button("← Back to shortlist",on_click=on_back)
    st.title(player_name(row))
    st.write(f"{row['club']} · {row['league']} · {row['season']} · ID {row['player_id']}")
    st.write(f"**Playable positions:** {row.get('positions_raw',row.get('position','—'))}")
    age,minutes,apps = st.columns(3)
    age.metric("Age",field_value(row.get("age")))
    minutes.metric("Minutes",field_value(row.get("minutes")))
    apps.metric("Appearances",field_value(row.get("appearances")))
    scope = provenance.get("competition_scope","Competition scope unconfirmed")
    st.caption(f"{scope.capitalize()} · Snapshot: {provenance.get('export_in_game_date',row['season'])}")

    if scored_row is not None:
        st.subheader("Current model")
        st.metric("Role index",f"{scored_row['role_index']:.1f}")
        st.html(profile_stats_html(row,weights,{metric:scored_row[f"{metric}_percentile"] for metric in weights},weights))
    st.caption("Percentiles compare this player with the current model's unfiltered benchmark. Missing values are excluded per statistic. Higher values rank higher, except lower-is-better metrics; chosen metrics use your configured direction. Totals and appearances reflect volume, not playing quality. Player details and unavailable statistics have no percentile.")

    covered = set()
    st.subheader("Season totals & appearances")
    fields = [field for field in FIELD_LABELS if field in row.index]
    covered.update(fields)
    stat_table(fields)
    for group in GROUPS:
        fields = [field for field,spec in METRIC_CATALOG.items() if spec.group==group and field in row.index]
        if fields:
            st.subheader(group)
            stat_table(fields)
            covered.update(fields)
    # Include uncatalogued metrics and context: new imported fields cannot vanish
    # just because the profile's friendly label catalogue has not yet caught up.
    remaining = [field for field in row.index if field not in covered]
    with st.expander("Player details & remaining fields",expanded=True):
        show_table(pd.DataFrame([{"Field":field_label(field),"Value":field_value(row[field])} for field in remaining]),hide_index=True,width="stretch")
    with st.expander("Complete source record"):
        show_table(pd.DataFrame({"Source field":row.index,"Recorded value":[field_value(value) for value in row]}),hide_index=True,width="stretch")
    st.download_button("Download player record",row.to_frame().T.to_csv(index=False).encode("utf-8"),
                       f"player_{row['player_id']}_{row['season'].replace('/','-')}.csv","text/csv")
