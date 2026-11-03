"""Small display helpers; the stored source data is left unchanged."""
import altair as alt
import pandas as pd
from scouting.nationalities import name_with_flag
from scouting.percentiles import display_percentile


def player_name(row):
    raw = str(row.get("name", ""))
    if raw.startswith("Unknown player (FM ID ") or not raw.replace("-", "").strip():
        return f"FM ID {row['player_id']}"
    return name_with_flag(raw)


def player_option(row):
    name = player_name(row)
    suffix = "" if name == f"FM ID {row['player_id']}" else f" · {row['player_id']}"
    return f"{name}{suffix} · {row['club']}"


def shortlist_table(frame, similarity=False):
    columns = ["name", "role_index", "club", "age", "minutes", "league", "player_id"]
    if "positions_raw" in frame:
        columns.append("positions_raw")
    else:
        columns.append("position")
    if similarity:
        columns = ["similarity_rank", "name", "profile_similarity", *[name for name in columns if name != "name"]]
    else:
        columns = ["cohort_rank", *columns]
    table = frame[columns].copy()
    table["name"] = frame.apply(player_name,axis=1)
    return table.rename(columns={"player_id":"ID", "name":"Player", "club":"Club", "league":"League",
        "positions_raw":"Positions", "position":"Positions", "age":"Age", "minutes":"Minutes",
        "role_index":"Role index", "cohort_rank":"Rank", "similarity_rank":"Match",
        "profile_similarity":"Profile similarity"}).round(2)


def percentile_chart(selected, weights, labels):
    rows = [{"Metric":labels[metric], "Player":player_option(row), "Percentile":float(row[f"{metric}_percentile"]),
             "Displayed percentile":display_percentile(row[f"{metric}_percentile"])}
            for _,row in selected.iterrows() for metric in weights]
    chart = alt.Chart(pd.DataFrame(rows)).mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("Percentile:Q",scale=alt.Scale(domain=[0,100]),title="Role percentile"),
        y=alt.Y("Metric:N",sort=list(labels.values()),title=None,axis=alt.Axis(labelLimit=270)),
        yOffset="Player:N", color=alt.Color("Player:N",legend=alt.Legend(orient="bottom",labelLimit=420),scale=alt.Scale(scheme="tableau10")),
        tooltip=["Player:N","Metric:N",alt.Tooltip("Displayed percentile:Q",title="Percentile",format=".2f")],
    ).properties(height=max(200, len(weights)*len(selected)*24)).configure_legend(labelFont="Source Sans")
    return chart
