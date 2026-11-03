"""Presentation-only helpers: scoring and stored player data stay untouched."""
from html import escape
import math
import pandas as pd
from scouting.views import player_name, shortlist_table
from scouting.percentiles import display_percentile

SHORT_LABELS = {
    "xa_p90":"xA /90", "key_passes_p90":"Key passes /90", "progressive_passes_p90":"Prog. passes /90",
    "xg_p90":"xG /90", "npxg_p90":"Non-penalty xG /90", "progressive_carries_p90":"Prog. carries /90",
    "box_receptions_p90":"Box receptions /90", "interceptions_p90":"Interceptions /90",
    "headers_won_p90":"Headers won /90", "tackles_completed_p90":"Tackles /90",
    "pass_completion_pct":"Pass completion %", "possession_lost_p90":"Possession lost /90",
    "possession_won_p90":"Possession won /90", "crosses_completed_p90":"Crosses /90",
    "shots_on_target_p90":"Shots on target /90", "goals_p90":"Goals /90", "passes_completed_p90":"Passes /90",
}


def compact_label(metric,labels):
    return SHORT_LABELS.get(metric,labels[metric])


def player_card_html(row,weights,labels):
    """Escape all source strings before inserting them into owned markup."""
    name = escape(player_name(row))
    club = escape(str(row["club"]))
    pid = escape(str(row["player_id"]))
    positions = row.get("positions_raw",row.get("position",""))
    positions = escape(str(positions)) if pd.notna(positions) and str(positions).strip() else "Positions unavailable"
    score = float(row["role_index"])
    rank = int(row["cohort_rank"])
    age = "Age unknown" if pd.isna(row["age"]) else f"{int(row['age'])} years"
    rows = []
    for metric in weights:
        percentile = float(row[f"{metric}_percentile"])
        width = max(0,min(100,percentile))
        tone = "strong" if percentile>=75 else "steady" if percentile>=50 else "muted"
        label = escape(compact_label(metric,labels))
        value = f"{row[metric]:.1f}%" if metric.endswith("_pct") else f"{row[metric]:.2f}"
        display = display_percentile(percentile)
        title = escape(f"{labels[metric]}: {value}; role percentile {display:.2f}")
        rows.append(f'<div class="player-stat" title="{title}"><div class="stat-line"><span>{label}</span><span><b>{value}</b><small>{display:.2f} pctl</small></span></div><div class="stat-track"><div class="stat-fill {tone}" style="width:{width:.2f}%"></div></div></div>')
    return (f'<article class="player-card" aria-label="{name}"><div class="card-top"><span class="rank-tag">#{rank}</span>'
            f'<span class="score-badge" title="Role index">{score:.1f}<small>INDEX</small></span></div>'
            f'<div class="player-title" title="{name}">{name}</div><div class="player-club">{club}</div>'
            f'<div class="player-meta">{age} <span>·</span> {row["minutes"]:,.0f} min</div>'
            f'<div class="player-meta" title="Listed playable positions">ID {pid} <span>·</span> {positions}</div>'
            f'<div class="player-stats">{"".join(rows)}</div></article>')


def shortlist_details(frame,weights,labels,mode):
    table = shortlist_table(frame)
    offset = 3
    for metric in weights:
        label = compact_label(metric,labels)
        if mode in ("Raw stats","All details"):
            table.insert(offset,label,frame[metric].round(2))
            offset += 1
        if mode in ("Percentiles","All details"):
            table.insert(offset,f"{label} · pctl",frame[f"{metric}_percentile"].map(display_percentile))
            offset += 1
    return table


def card_page(frame,page=1,page_size=6):
    pages = max(1,math.ceil(len(frame)/page_size))
    page = min(max(1,int(page)),pages)
    return frame.iloc[(page-1)*page_size:page*page_size],pages
