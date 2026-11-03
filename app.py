"""Run with: python -m streamlit run app.py"""
from pathlib import Path
from datetime import date
import json
import pandas as pd
import streamlit as st

from scouting.data import CSVPlayerSource
from scouting.roles import BASE_MINUTES, LABELS, ROLE_NAME, WEIGHTS
from scouting.scoring import filter_players, score_players
from scouting.statsbomb import DATASETS, import_season
from scouting.fm_roles import ROLE_PROFILES, METRIC_LABELS, POSITION_LABELS, RoleProfile, position_capabilities, score_fm_role
from scouting.custom_models import METRIC_CATALOG,GROUPS,DEFAULT_METRICS,available_metrics,normalise_weights,score_custom_model,model_config
from scouting.similarity import find_similar_players, metric_gaps
from scouting.views import player_name, player_option, shortlist_table, percentile_chart
from scouting.presentation import player_card_html,shortlist_details,compact_label,card_page
from scouting.appearance import chart_theme
from scouting.percentiles import display_percentile
from scouting.player_profile import render_player_profile

st.set_page_config(page_title="Touchline | Football scouting", page_icon="⚽", layout="wide",initial_sidebar_state="collapsed")
root = Path(__file__).parent
with st.container(key="workspace_header"):
    brand,appearance = st.columns([3,1],vertical_alignment="center")
    dark_mode = appearance.toggle("Dark mode",value=True,key="dark_mode")
    with brand:
        st.html('<div class="workspace-brand"><div class="workspace-mark">T</div><div><div class="workspace-title">Touchline</div><div class="workspace-kicker">SCOUTING WORKSPACE</div></div></div>')
theme_css = (root/'assets/theme.css').read_text(encoding='utf-8')
theme_css += "\n"+(root/'assets/flags-font.css').read_text(encoding='utf-8')
if dark_mode:
    theme_css += "\n"+(root/'assets/dark.css').read_text(encoding='utf-8')
st.html(f"<style>{theme_css}</style>")
# Native grid colours pass through the dark canvas transform.
scale_color = "#004186" if dark_mode else "#198467"


def read_metadata(path):
    metadata_path = path.with_suffix(".json")
    return json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}


sources = {"sample_players.csv": root / "data/sample_players.csv"}
sources.update({p.name:p for pattern in ("statsbomb_*.csv","fm24_*.csv") for p in sorted((root/"data").glob(pattern))})
try:
    source_metadata = {name:read_metadata(path) for name,path in sources.items()}
except (OSError,ValueError) as error:
    st.error(f"Could not read dataset details: {error}")
    st.stop()
fm_sources = [name for name in sources if name.startswith("fm24_")]
default_source = max(fm_sources,key=lambda name:source_metadata[name].get("imported_at_utc","")) if fm_sources else "sample_players.csv"
requested = st.query_params.get("dataset",st.session_state.get("active_source",default_source))

st.sidebar.header("Refine your search")
with st.sidebar.expander("Dataset & imports"):
    source_name = st.selectbox("Player dataset",list(sources),
        index=list(sources).index(requested) if requested in sources else 0,
        format_func=lambda name: "Fictional sample" if name=="sample_players.csv" else source_metadata[name].get("dataset",name))
    with st.expander("Download StatsBomb data"):
        dataset = st.selectbox("Competition to import",list(DATASETS))
        if st.button("Import StatsBomb season"):
            progress = st.progress(0,text="Reading match catalogue…")
            try:
                path,_ = import_season(dataset,root,progress=lambda n,total:progress.progress(n/total,text=f"Match {n} of {total}"))
            except (OSError,ValueError,KeyError,TypeError) as error:
                st.error(f"Import stopped: {error}. Completed downloads are cached.")
            else:
                st.session_state["active_source"] = path.name
                st.rerun()

fm_data, real_data = source_name.startswith("fm24_"),source_name.startswith("statsbomb_")
provenance = source_metadata[source_name]
try:
    players = pd.read_csv(sources[source_name],dtype={"player_id":str}) if fm_data else CSVPlayerSource(sources[source_name]).load()
except (OSError,ValueError,pd.errors.ParserError) as error:
    st.error(f"Could not load player data: {error}")
    st.stop()

season = st.sidebar.selectbox("Season",sorted(players["season"].unique()))
season_players = players.loc[players["season"].eq(season)]
role_key,lower_is_better = "creative",()
custom_mode = False
if fm_data:
    custom_mode = st.sidebar.selectbox("Model setup",["Choose my metrics","Position presets"],key=f"model_setup:{source_name}")=="Choose my metrics"
    if custom_mode:
        available = available_metrics(season_players)
        selected_metrics = []
        with st.sidebar.expander("Choose metrics",expanded=True):
            for group in GROUPS:
                st.caption(group.upper())
                options = [metric for metric,spec in available.items() if spec.group==group]
                if options:
                    selected_metrics.extend(st.multiselect(f"{group} metrics",options,
                        default=[metric for metric in DEFAULT_METRICS if metric in options],
                        format_func=lambda metric:METRIC_CATALOG[metric].label,
                        key=f"metrics:{source_name}:{group}",label_visibility="collapsed"))
                else:
                    st.caption("No metrics available in this dataset.")
            st.caption("PHYSICAL")
            st.caption("No sprint, running-distance or high-intensity movement data in this export.")
        if not selected_metrics:
            st.info("Choose at least one metric in the sidebar to build your index.")
            st.stop()
        importance = {}
        lower_metrics = []
        with st.sidebar.expander("Weights & direction"):
            st.caption("Importance is relative; equal values give equal weights.")
            for metric in selected_metrics:
                spec = METRIC_CATALOG[metric]
                importance_key = f"importance:{source_name}:{metric}"
                if importance_key not in st.session_state:
                    st.session_state[importance_key] = 1
                importance[metric] = st.number_input(f"{spec.label} · importance",min_value=1,max_value=10,value=None,
                    key=importance_key,help=spec.note or None) or 1
                preferred = st.selectbox(f"{spec.label} · better when",["Higher","Lower"],
                    index=1 if spec.lower_is_better else 0,key=f"direction:{source_name}:{metric}")
                if preferred=="Lower":
                    lower_metrics.append(metric)
        include_goalkeepers = st.sidebar.checkbox("Include goalkeepers in custom benchmark",value=False,key=f"custom_gk:{source_name}")
        WEIGHTS = normalise_weights(selected_metrics,importance)
        LABELS = {metric:METRIC_CATALOG[metric].label for metric in WEIGHTS}
        lower_is_better = tuple(lower_metrics)
        ROLE_NAME = "Custom performance index"
        scored = score_custom_model(season_players,WEIGHTS,lower_is_better,include_goalkeepers)
        config = model_config(WEIGHTS,lower_is_better,include_goalkeepers)
        role_key = scored.role_key.iloc[0] if not scored.empty else "custom_empty"
        profile = RoleProfile(ROLE_NAME,(),WEIGHTS,
            "Your selected performance metrics define this index. Positions remain a separate shortlist filter; the custom benchmark is all eligible outfield players unless goalkeepers are included.",lower_is_better)
    else:
        role_key = st.sidebar.selectbox("Position / role model",list(ROLE_PROFILES),format_func=lambda key:ROLE_PROFILES[key].name,key=f"role_model:{source_name}")
        profile = ROLE_PROFILES[role_key]
        WEIGHTS,ROLE_NAME,lower_is_better = profile.weights,profile.name,profile.lower_is_better
        LABELS = {metric:METRIC_LABELS[metric] for metric in WEIGHTS}
        scored = score_fm_role(season_players,role_key)
else:
    scored = score_players(season_players,WEIGHTS)

model_widget_scope = "custom" if custom_mode else role_key
context = f"FM24 simulation · {provenance.get('competition_scope','Unconfirmed competition scope').capitalize()}" if fm_data else "StatsBomb match data" if real_data else "Fictional sample data"
snapshot_date = date.fromisoformat(provenance['export_in_game_date']).strftime('%d %b %Y') if provenance.get("export_in_game_date") else season
st.caption(f"{context} · {snapshot_date} · {len(players):,} players")
if not st.query_params.get("player"):
    st.subheader(ROLE_NAME)
if fm_data and role_key=="goalkeeper":
    st.info("Distribution only — shot-stopping statistics are unavailable.")
if scored.empty:
    st.info("No players have 900+ minutes and every selected metric. Remove a metric or choose another model or dataset.")
    st.stop()

leagues = st.sidebar.multiselect("Leagues",sorted(scored.league.unique()),default=sorted(scored.league.unique()))
with st.sidebar.expander("Position, age & minutes"):
    position_options = sorted(set().union(*(set(value.split("|")) for value in scored.position_memberships))) if fm_data else sorted(scored.position.unique())
    positions = st.multiselect("Positions",position_options,default=position_options,
        format_func=lambda code:f"{code} · {POSITION_LABELS.get(code,code)}" if fm_data else code,key=f"positions:{source_name}:{model_widget_scope}")
    ages = st.slider("Age range",14,60,(14,60) if fm_data else (18,30))
    include_unknown = st.checkbox("Include unknown ages",value=True)
    minutes = st.slider("Minimum minutes",BASE_MINUTES,max(BASE_MINUTES+1,int(scored.minutes.max())),BASE_MINUTES,step=100)
query = st.sidebar.text_input("Search player name or ID",help="Filters shortlist and similarity candidates. Choose your reference player in Similar players.")
visible = filter_players(scored,leagues,positions,ages,minutes,query,include_unknown)
lookup = scored.set_index("player_id",drop=False)


def show_chart(selected):
    chart = chart_theme(percentile_chart(selected,WEIGHTS,LABELS),dark_mode)
    st.altair_chart(chart,width="stretch",theme=None if dark_mode else "streamlit")


def show_table(data,**options):
    # The dark stylesheet transforms the entire native grid, including its
    # canvas headers and empty cells. Cell-only Styler colours leave white gaps.
    return st.dataframe(data,**options)


def raw_comparison(selected):
    table = selected[["role_index",*WEIGHTS]].T
    table.columns = [player_option(row) for _,row in selected.iterrows()]
    return table.rename(index={**LABELS,"role_index":"Role index"}).round(3)


def set_comparison(key,ids):
    st.session_state[key] = ids
    st.toast("Comparison updated. Open the Compare tab.")


def open_profile(pid):
    # Streamlit clears widgets that are absent on another page. Save the main
    # workspace selections explicitly so returning preserves pagination/models.
    prefixes = ("page:","card_count:","shortlist_view:","compare:","inspect:","model_importance:",
                "reference:","limit:","match:")
    st.session_state["profile_return_state"] = {name:st.session_state[name] for name in st.session_state
                                                if name.startswith(prefixes)}
    st.query_params["player"] = str(pid)
    st.query_params["dataset"] = source_name


def return_to_shortlist():
    st.query_params.pop("player",None)
    st.query_params.pop("dataset",None)
    for key,value in st.session_state.pop("profile_return_state",{}).items():
        st.session_state[key] = value


profile_id = st.query_params.get("player")
if profile_id and st.query_params.get("dataset",source_name)==source_name:
    matching = season_players.loc[season_players.player_id.eq(profile_id)]
    if matching.empty:
        st.button("← Back to shortlist",on_click=return_to_shortlist)
        st.info("This player is not in the selected dataset and season.")
    else:
        render_player_profile(matching.iloc[0],lookup.loc[profile_id] if profile_id in lookup.index else None,
                              WEIGHTS,provenance,show_table,return_to_shortlist,scored,lower_is_better)
    st.stop()

with st.container(key="summary_strip"):
    a,b,c = st.columns(3)
    a.metric("Matches",len(visible))
    b.metric("Benchmark",len(scored))
    c.metric("Metrics",len(WEIGHTS))

shortlist_tab,compare_tab,similar_tab,database_tab,model_tab = st.tabs(["Shortlist","Compare","Similar players","Database","Model & data"])


with shortlist_tab:
    view_key = f"shortlist_view:{source_name}"
    if view_key not in st.session_state:
        st.session_state[view_key] = "Player cards"
    view = st.segmented_control("Shortlist view",["Player cards","Percentiles","Raw stats","All details"],
        default=None,required=True,key=view_key,label_visibility="collapsed")
    if visible.empty:
        st.info("No matches. Widen your filters to see players.")
    else:
        inspect_key = f"inspect:{source_name}:{model_widget_scope}"
        if view=="Player cards":
            with st.container(key="card_paging"):
                size_control,page_control = st.columns(2)
                page_size = size_control.selectbox("Cards per page",[6,12,24,48],key=f"card_count:{source_name}")
                _,pages = card_page(visible,page_size=page_size)
                page = page_control.selectbox("Page",list(range(1,pages+1)),format_func=lambda value:f"{value} of {pages}",key=f"page:{source_name}:{role_key}:{page_size}")
            page_players,_ = card_page(visible,page,page_size)
            st.caption(f"{len(visible)} players · {(page-1)*page_size+1}–{min(page*page_size,len(visible))} shown")
            with st.container(key="player_grid"):
                for start in range(0,len(page_players),4):
                    columns = st.columns(4,gap="medium")
                    for column,(_,row) in zip(columns,page_players.iloc[start:start+4].iterrows()):
                        with column:
                            with st.container(border=True,key=f"shortlist_card_{source_name}_{role_key}_{row['player_id']}"):
                                st.html(player_card_html(row,WEIGHTS,LABELS))
                                st.button("View profile",key=f"open:{source_name}:{role_key}:{row['player_id']}",
                                    on_click=open_profile,args=(row['player_id'],),width="stretch")
        else:
            metric_columns = {}
            for metric in WEIGHTS:
                label = compact_label(metric,LABELS)
                direction = "Lower" if metric in lower_is_better else "Higher"
                metric_columns[label] = st.column_config.NumberColumn(label,format="%.2f",
                    help=f"{LABELS[metric]} · {WEIGHTS[metric]*100:g}% of the index · {direction} is better")
                metric_columns[f"{label} · pctl"] = st.column_config.ProgressColumn(f"{label} · pctl",
                    min_value=0,max_value=100,format="%.2f",color=scale_color,help="Role percentile, shown to two decimal places without rounding up. Higher is stronger. Filters keep the reference group fixed.")
            show_table(shortlist_details(visible,WEIGHTS,LABELS,view),hide_index=True,width="stretch",
                column_config={"Role index":st.column_config.ProgressColumn("Role index",min_value=0,max_value=100,format="%.1f",color=scale_color),**metric_columns})
        if inspect_key in st.session_state and st.session_state[inspect_key] not in set(visible.player_id):
            st.session_state[inspect_key] = None
        inspect_id = st.selectbox("Open a player profile",list(visible.player_id),index=None,placeholder="Search by name or FM ID…",
            format_func=lambda pid:player_option(lookup.loc[pid]),key=inspect_key)
        if inspect_id is not None:
            row = lookup.loc[inspect_id]
            with st.container(border=True):
                st.subheader(player_name(row))
                st.caption(f"{row['club']} · ID {inspect_id} · Role index {row['role_index']:.1f}")
                breakdown = pd.DataFrame([{"Statistic":LABELS[metric],"Value":row[metric],"Percentile":display_percentile(row[f"{metric}_percentile"])} for metric in WEIGHTS])
                show_table(breakdown.round(2),hide_index=True,width="stretch",column_config={"Percentile":st.column_config.ProgressColumn("Percentile",min_value=0,max_value=100,format="%.2f",color=scale_color)})
        st.download_button("Download shortlist",visible.to_csv(index=False).encode("utf-8"),f"scouting_{role_key}_rankings.csv","text/csv")

compare_key = f"compare:{source_name}:{model_widget_scope}"
with compare_tab:
    st.caption("Compare up to three players from this role group. Search by name or FM ID.")
    if compare_key in st.session_state:
        valid = [pid for pid in st.session_state[compare_key] if pid in lookup.index][:3]
        if valid != st.session_state[compare_key]:
            st.session_state[compare_key] = valid
    else:
        st.session_state[compare_key] = list(lookup.index[:2])
    chosen = st.multiselect("Players",list(lookup.index),max_selections=3,
        key=compare_key,format_func=lambda pid:player_option(lookup.loc[pid]))
    if chosen:
        selected = lookup.loc[chosen]
        for column,(_,row) in zip(st.columns(len(selected)),selected.iterrows()):
            with column:
                with st.container(border=True):
                    st.write(player_name(row))
                    st.caption(f"{row['club']} · ID {row['player_id']}")
                    st.metric("Role index",f"{row['role_index']:.1f}")
                    age = "Unknown age" if pd.isna(row["age"]) else f"Age {int(row['age'])}"
                    st.caption(f"{age} · {row['minutes']:,.0f} minutes")
        show_chart(selected)
        with st.expander("Detailed statistics"):
            show_table(raw_comparison(selected),width="stretch")
        with st.expander("Score contributions"):
            contributions = pd.DataFrame({player_option(row):[row[f"{metric}_contribution"] for metric in WEIGHTS] for _,row in selected.iterrows()},index=list(LABELS.values()))
            show_table(contributions.round(2),width="stretch")
        st.download_button("Download comparison",selected.to_csv(index=False).encode("utf-8"),f"comparison_{role_key}.csv","text/csv")
    else:
        st.info("Choose players above to compare their profiles.")

with similar_tab:
    st.caption("Find nearby performance profiles in this role group. Similarity is separate from the role index.")
    reference_key = f"reference:{source_name}:{model_widget_scope}"
    if reference_key in st.session_state and st.session_state[reference_key] not in lookup.index:
        st.session_state[reference_key] = lookup.index[0]
    reference_id = st.selectbox("Reference player",list(lookup.index),format_func=lambda pid:player_option(lookup.loc[pid]),key=reference_key)
    limit_key = f"limit:{source_name}:{model_widget_scope}"
    if limit_key not in st.session_state:
        st.session_state[limit_key] = 10
    limit = st.selectbox("Matches to show",[5,10,20,30],index=None,key=limit_key) or 10
    similar = find_similar_players(scored,reference_id,WEIGHTS,candidate_ids=visible.player_id,limit=limit)
    st.caption("Candidates follow sidebar filters; the reference player can be outside those filters.")
    if similar.empty:
        st.info("No other players match your filters. Widen them to find alternatives.")
    else:
        show_table(shortlist_table(similar,similarity=True),hide_index=True,width="stretch",
            column_config={"Profile similarity":st.column_config.ProgressColumn("Profile similarity",min_value=0,max_value=100,format="%.1f",color=scale_color)})
        st.download_button("Download similar players",similar.to_csv(index=False).encode("utf-8"),f"similar_to_{reference_id}_{role_key}.csv","text/csv")
        match_id = st.selectbox("Inspect a match",list(similar.player_id),format_func=lambda pid:player_option(lookup.loc[pid]),key=f"match:{source_name}:{role_key}:{reference_id}")
        gaps = metric_gaps(lookup.loc[reference_id],lookup.loc[match_id],WEIGHTS,LABELS)
        closest = gaps.loc[gaps["Percentile gap"].idxmin(),"Metric"]
        largest = gaps.loc[gaps["Percentile gap"].idxmax(),"Metric"]
        st.caption(f"Closest metric: {closest} · Largest gap: {largest}")
        st.button("Compare this pair",on_click=set_comparison,args=(compare_key,[reference_id,match_id]),key=f"pair:{source_name}:{role_key}")
        with st.expander("Why this match?"):
            show_chart(lookup.loc[[reference_id,match_id]])
            gaps_display = gaps.round(3)
            for column in ("Reference percentile","Match percentile"):
                gaps_display[column] = gaps[column].map(display_percentile)
            show_table(gaps_display,hide_index=True,width="stretch")
    with st.expander("How similarity works"):
        st.write("We compare the players' percentiles on this model's metrics, using the same metric weights. Smaller weighted gaps give a higher profile similarity, on a 0–100 scale. The reference player is excluded. Age, club, name and overall role index are not part of the distance calculation.")
        st.code("distance = sqrt(sum(weight × percentile_gap²))\nsimilarity = 100 − distance",language=None)
        st.caption("This compares observed statistical profiles, including their performance levels. It is not a probability, a pure playing-style measure, or a prediction that a transfer will succeed.")

with database_tab:
    browse_query = st.text_input("Find a player by ID or name",key="browse_query")
    browse_leagues = st.multiselect("Club divisions to browse",sorted(players.league.unique()),default=sorted(players.league.unique()),key="browse_leagues")
    browse = players.loc[players.league.isin(browse_leagues)]
    if fm_data:
        all_codes = sorted(set().union(*(position_capabilities(value) for value in players.positions_raw)))
        with st.expander("Position & column filters"):
            browse_positions = st.multiselect("Listed positions to browse",all_codes,default=all_codes,key="browse_positions",
                format_func=lambda code:f"{code} · {POSITION_LABELS.get(code,code)}")
            chosen_positions = set(browse_positions)
            browse = browse.loc[browse.positions_raw.map(lambda value:bool(position_capabilities(value)&chosen_positions))]
            defaults = [name for name in ["player_id","name","club","league","positions_raw","age","minutes","appearances","goals","assists","xa_p90","xg_p90"] if name in players]
            browse_columns = st.multiselect("Database columns",list(players.columns),default=defaults,key=f"database_columns:{source_name}")
    else:
        browse_columns = list(players.columns)
    if browse_query.strip():
        browse = browse.loc[browse.player_id.str.contains(browse_query.strip(),regex=False)|browse.name.str.contains(browse_query.strip(),case=False,regex=False)]
    st.caption(f"{len(browse):,} of {len(players):,} players · Includes every position and minutes level")
    if browse_columns:
        browse_display = browse[browse_columns].copy()
        if "name" in browse_display:
            browse_display["name"] = browse.apply(player_name,axis=1)
        show_table(browse_display,hide_index=True,width="stretch")
    else:
        st.info("Choose at least one database column.")
    st.download_button("Download database selection",browse.to_csv(index=False).encode("utf-8"),"database_selection.csv","text/csv")

with model_tab:
    if custom_mode:
        st.subheader("Metric weights")
        st.caption("Adjust relative importance from 1–10. The percentage weights below update automatically.")

        def update_model_weight(metric,editor_key):
            st.session_state[f"importance:{source_name}:{metric}"] = st.session_state[editor_key] or 1

        weight_columns = st.columns(2)
        for index,metric in enumerate(WEIGHTS):
            editor_key = f"model_importance:{source_name}:{metric}"
            # Keep the tab editor in sync when its sidebar counterpart changes.
            st.session_state[editor_key] = importance[metric]
            with weight_columns[index%2]:
                st.number_input(f"{LABELS[metric]} · weight",min_value=1,max_value=10,value=None,
                    key=editor_key,on_change=update_model_weight,args=(metric,editor_key),
                    help="Relative importance. All chosen weights are normalised to total 100%.")
    show_table(pd.DataFrame({"Metric":list(LABELS.values()),"Weight (%)":[weight*100 for weight in WEIGHTS.values()],
        "Preferred direction":["Lower" if metric in lower_is_better else "Higher" for metric in WEIGHTS]}),hide_index=True,width="stretch")
    with st.expander("Scoring method & limitations"):
        if custom_mode:
            st.write("Your index is the weighted sum of your selected metric percentiles. The benchmark uses all eligible outfield players in this snapshot with at least 900 minutes and every selected metric, unless you include goalkeepers. Position, league, age and search filters narrow candidates without recalculating that benchmark. Changing the metrics, directions or weights rebuilds the custom index and similarity model.")
        else:
            st.write("Role index = weighted metric percentiles. The reference group uses the selected role, one season, at least 900 minutes and complete model metrics. Filters narrow results without changing those reference scores. Each role has a separate cohort; indices from different roles are not directly comparable.")
        st.code("percentile = 100 × (average_rank − 0.5) / reference_players\nrole_index = sum(percentile × weight)",language=None)
        st.write("Better values receive higher percentiles according to the model's preferred direction. Ties share a rank and constant metrics give everyone 50. Missing statistics are not replaced with zero. Scores from different benchmarks or metric configurations are not directly comparable.")
        st.caption("Displayed percentiles are truncated to two decimal places so they never round up to 100. Calculations and downloads retain full precision.")
        if fm_data:
            st.write(profile.note)
            st.write("Statistics are FM24 simulated all-competitions performance. Club division does not restrict statistics to that league. No league-strength or possession adjustment is applied. Eligibility uses listed position capabilities, not position-specific match minutes. Existing /90 values are retained. Goals and xG include penalties; attributes are never used.")
        elif real_data:
            st.write("StatsBomb chance creation uses assisted-shot xG. Progression uses our own 10m distance-reduction rule; box receptions count successful reception events. See the data provenance for exact definitions.")
        st.caption("Weights are provisional. Scores and similarity do not establish recruitment success.")
    if custom_mode:
        config_export = {**config,"dataset":source_name,"source_sha256":provenance.get("source_sha256"),"season":season,"snapshot_date":provenance.get("export_in_game_date"),"minimum_minutes":BASE_MINUTES}
        st.download_button("Download custom model settings",json.dumps(config_export,indent=2).encode("utf-8"),"custom_model_settings.json","application/json")
    with st.expander("Dataset details"):
        st.json(provenance if provenance else {"dataset":"Fictional sample","players":len(players)})
    if fm_data:
        with st.expander("All position models"):
            role_tables = {key:score_fm_role(season_players,key) for key in ROLE_PROFILES}
            show_table(pd.DataFrame([{"Model":role.name,"Positions":", ".join(role.positions),"Ranked players":len(role_tables[key])} for key,role in ROLE_PROFILES.items()]),hide_index=True,width="stretch")
            all_rankings = pd.concat(role_tables.values(),ignore_index=True)
            st.download_button("Download every position model",all_rankings.to_csv(index=False).encode("utf-8"),"all_position_indices.csv","text/csv")
