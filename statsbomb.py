"""Turn StatsBomb open match JSON into our provider-independent player table.

Downloads are explicit, resumable and cached. Aggregation is separately testable.
"""
from collections import Counter
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
from scouting.data import validate_players

BASE_URL = "https://raw.githubusercontent.com/hudl/open-data/master/data"
DATASETS = {
    "Bundesliga 2023/24": (9, 281),
    "Women's Super League 2023/24": (37, 281),
}
METRICS = ["xa_p90", "key_passes_p90", "progressive_passes_p90",
           "progressive_carries_p90", "npxg_p90", "box_receptions_p90"]
POSITION_MAP = {
    1: "GK", 2: "RB", 3: "CB", 4: "CB", 5: "CB", 6: "LB",
    7: "RWB", 8: "LWB", 9: "DM", 10: "DM", 11: "DM",
    12: "RW", 13: "CM", 14: "CM", 15: "CM", 16: "LW",
    17: "RW", 18: "AM", 19: "AM", 20: "AM", 21: "LW",
    22: "ST", 23: "ST", 24: "ST", 25: "ST",
}


def read_json(relative_path, cache_dir):
    """Reuse completed downloads; never cache a failed or invalid response."""
    path = Path(cache_dir) / relative_path
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    request = Request(f"{BASE_URL}/{relative_path}", headers={"User-Agent": "Touchline-learning-project/0.2"})
    with urlopen(request, timeout=30) as response:
        payload = response.read().decode("utf-8")
    parsed = json.loads(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(payload, encoding="utf-8")
    temp.replace(path)
    return parsed


def clock_minutes(value):
    minutes, seconds = value.split(":")
    return int(minutes) + float(seconds) / 60


def period_boundaries(events):
    """Match clocks reset to 45/90/105 at period starts; retain stoppage time."""
    ends = {}
    for event in events:
        period = event.get("period", 0)
        if event.get("type", {}).get("name") == "Half End" and period <= 4:
            ends[period] = max(ends.get(period, 0), event["minute"] + event["second"] / 60)
    if set(ends) != {1, 2}:
        raise ValueError("This league importer requires both Half End events and no extra time.")
    return ends


def elapsed(time_value, period, ends):
    bases = {1: 0, 2: 45}
    prior = sum(ends[p] - bases[p] for p in range(1, period))
    return prior + clock_minutes(time_value) - bases[period]


def in_box(location):
    # StatsBomb coordinates: pitch 120 x 80, attacking goal at (120, 40).
    return bool(location and len(location) >= 2 and 102 <= location[0] <= 120 and 18 <= location[1] <= 62)


def progressive(start, end):
    """Our own threshold: reduce distance to goal centre by at least 10m.

    Scale the 120x80 grid to an assumed 105x68m pitch. This is not a
    Wyscout/FBref progression definition and must not be presented as one.
    """
    if not start or not end or len(start) < 2 or len(end) < 2:
        return False
    def distance(point):
        return math.hypot((120 - point[0]) * 105 / 120, (40 - point[1]) * 68 / 80)
    return distance(start) - distance(end) >= 10


class SeasonAggregator:
    def __init__(self, league, season, reference_date):
        self.league = league
        self.season = season
        self.reference_date = date.fromisoformat(reference_date)
        self.players = {}
        self.matches = set()

    def add_match(self, match_id, events, lineups):
        if match_id in self.matches:
            raise ValueError(f"Duplicate match: {match_id}")
        ends = period_boundaries(events)
        match_end = ends[1] + ends[2] - 45
        # Some source lineup files retain tactical shifts for dismissed players,
        # even in later periods. The actual dismissal event ends their appearance.
        dismissed_at = {}
        for event in events:
            card = event.get("foul_committed", {}).get("card", {}) or event.get("bad_behaviour", {}).get("card", {})
            if (card.get("name") in ("Red Card", "Second Yellow") or event.get("type", {}).get("name") == "Substitution") and "player" in event and event.get("period") in (1, 2):
                pid = str(event["player"]["id"])
                clock = f"{event['minute']}:{event['second']}"
                when = elapsed(clock, event["period"], ends)
                dismissed_at[pid] = min(dismissed_at.get(pid, match_end), when)
        active = set()
        for team in lineups:
            for player in team["lineup"]:
                spans = player.get("positions", [])
                if not spans:
                    continue  # unused substitutes have no appearance or minutes
                pid = str(player["player_id"])
                state = self.players.setdefault(pid, {
                    "name": player["player_name"], "dob": player.get("dob"),
                    "clubs": Counter(), "positions": Counter(), "minutes": 0.0,
                    "totals": Counter(), "appearances": 0,
                })
                if player.get("dob"):
                    if state["dob"] and state["dob"] != player["dob"]:
                        raise ValueError(f"Conflicting birth dates for {pid}.")
                    state["dob"] = player["dob"]
                intervals = []
                appearance_end = dismissed_at.get(pid, match_end)
                for span in spans:
                    start = elapsed(span["from"], span["from_period"], ends)
                    end = match_end if span["to"] is None else elapsed(span["to"], span["to_period"], ends)
                    if pid in dismissed_at:
                        if start >= appearance_end:
                            continue
                        end = min(end, appearance_end)
                    if start < 0 or end < start or end > match_end + 0.02:
                        raise ValueError(f"Invalid minutes interval for player {pid} in match {match_id}: {span['from']} (period {span['from_period']}) to {span['to']} (period {span['to_period']}).")
                    if end > start:
                        intervals.append((start, end, POSITION_MAP.get(span["position_id"], "OTHER")))
                intervals.sort()
                merged = []
                for start, end, position in intervals:
                    if merged and start < merged[-1][1]:
                        last_start, last_end, last_position = merged[-1]
                        if position != last_position and start < last_end - 0.02:
                            raise ValueError(f"Conflicting position intervals for player {pid} in match {match_id}.")
                        if position == last_position:
                            merged[-1] = (last_start, max(last_end, end), position)
                            continue
                        start = last_end
                    merged.append((start, end, position))
                minutes = sum(end - start for start, end, _ in merged)
                for start, end, position in merged:
                    state["positions"][position] += end - start
                if minutes > 0:
                    state["minutes"] += minutes
                    state["clubs"][team["team_name"]] += minutes
                    state["appearances"] += 1
                    active.add(pid)

        shots = {event["id"]: event for event in events if event.get("type", {}).get("name") == "Shot" and event.get("period", 0) <= 2}
        for event in shots.values():
            xg = event["shot"].get("statsbomb_xg")
            if xg is None or not math.isfinite(xg) or not 0 <= xg <= 1:
                raise ValueError("A shot is missing valid xG; refusing to treat it as zero.")
        # Older files may link from the shot back to the pass instead.
        shot_by_pass = {event["shot"]["key_pass_id"]: event for event in shots.values() if event["shot"].get("key_pass_id")}
        for event in events:
            if event.get("period", 0) not in (1, 2) or "player" not in event:
                continue
            pid = str(event["player"]["id"])
            if pid not in active:
                raise ValueError(f"Event player {pid} is missing playing minutes in match {match_id}.")
            totals = self.players[pid]["totals"]
            kind = event["type"]["name"]
            if kind == "Shot" and event["shot"].get("type", {}).get("name") != "Penalty":
                totals["npxg_p90"] += event["shot"]["statsbomb_xg"]
            if kind == "Pass":
                info = event["pass"]
                linked_id = info.get("assisted_shot_id")
                linked = shots.get(linked_id) if linked_id else shot_by_pass.get(event["id"])
                if (linked_id or info.get("shot_assist")) and linked is None:
                    raise ValueError("A shot-assisting pass cannot be linked to its shot.")
                if linked is not None:
                    totals["key_passes_p90"] += 1
                    totals["xa_p90"] += linked["shot"]["statsbomb_xg"]
                if "outcome" not in info and progressive(event.get("location"), info.get("end_location")):
                    totals["progressive_passes_p90"] += 1
            if kind == "Carry" and progressive(event.get("location"), event["carry"].get("end_location")):
                totals["progressive_carries_p90"] += 1
            if kind == "Ball Receipt*" and "outcome" not in event.get("ball_receipt", {}) and in_box(event.get("location")):
                totals["box_receptions_p90"] += 1
        self.matches.add(match_id)

    def frame(self):
        rows = []
        for pid, player in self.players.items():
            if player["minutes"] <= 0:
                continue
            age = None
            if player["dob"]:
                dob = date.fromisoformat(player["dob"])
                age = self.reference_date.year - dob.year - ((self.reference_date.month, self.reference_date.day) < (dob.month, dob.day))
            rows.append({
                "player_id": pid, "name": player["name"],
                "club": " / ".join(sorted(player["clubs"])),
                "league": self.league, "season": self.season,
                "position": player["positions"].most_common(1)[0][0],
                "age": age, "minutes": round(player["minutes"], 4),
                **{metric: player["totals"][metric] / player["minutes"] * 90 for metric in METRICS},
            })
        return validate_players(pd.DataFrame(rows))


def import_season(dataset, project_root, progress=None, local_data=None):
    """Publish a CSV only after every listed available match is processed.

    local_data is the repository's data/ folder for a completely offline import.
    """
    competition_id, season_id = DATASETS[dataset]
    root = Path(project_root)
    cache_dir = Path(local_data) if local_data else root / "work" / "statsbomb"
    def get(relative):
        if local_data:
            return json.loads((cache_dir / relative).read_text(encoding="utf-8"))
        return read_json(relative, cache_dir)
    matches = get(f"matches/{competition_id}/{season_id}.json")
    if not matches or any(m.get("match_status") != "available" for m in matches):
        raise ValueError("Some listed matches lack available events; import stopped to avoid a partial season.")
    if len({m["match_id"] for m in matches}) != len(matches):
        raise ValueError("Duplicate match IDs in source catalogue.")
    reference_date = max(m["match_date"] for m in matches)
    first = matches[0]
    aggregator = SeasonAggregator(first["competition"]["competition_name"], first["season"]["season_name"], reference_date)
    for index, match in enumerate(sorted(matches, key=lambda m: m["match_id"])):
        if match["competition"]["competition_id"] != competition_id or match["season"]["season_id"] != season_id:
            raise ValueError("Catalogue contains a match from another competition or season.")
        mid = match["match_id"]
        events, lineups = get(f"events/{mid}.json"), get(f"lineups/{mid}.json")
        aggregator.add_match(mid, events, lineups)
        if progress:
            progress(index + 1, len(matches))
    frame = aggregator.frame()
    path = root / "data" / f"statsbomb_{competition_id}_{season_id}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "provider": "StatsBomb", "dataset": dataset, "source": "https://github.com/hudl/open-data",
        "competition_id": competition_id, "season_id": season_id,
        "imported_at_utc": datetime.now(timezone.utc).isoformat(),
        "match_count": len(matches), "match_ids": sorted(aggregator.matches),
        "first_match_date": min(m["match_date"] for m in matches), "last_match_date": reference_date,
        "age_reference_date": reference_date, "player_count": len(frame),
        "unknown_ages": int(frame["age"].isna().sum()),
        "coverage": "All matches listed in the repository catalogue; no claim of independently verified full-season coverage.",
        "minutes": "Actual playing time from lineup intervals and period-end events, capped at dismissal events; includes stoppage and excludes half-time.",
        "xa_p90": "Assisted-shot xG: sum of xG for shots directly linked to a player's passes; not a standalone pass-quality xA model.",
        "progression": "Completed passes / carries reducing distance to goal centre by >=10m, assuming a 105x68m pitch.",
        "box_receptions": "Successful Ball Receipt* events in x=102..120, y=18..62 on the 120x80 grid.",
        "position": "Broad position with most actual minutes across the imported matches.",
        "terms": "Review LICENSE.pdf; attribute StatsBomb and use its logo when publishing analysis, as requested in the repository README.",
    }
    csv_temp, meta_temp = path.with_suffix(".csv.tmp"), path.with_suffix(".json.tmp")
    frame.to_csv(csv_temp, index=False)
    meta_temp.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    meta_temp.replace(path.with_suffix(".json"))
    csv_temp.replace(path)
    return path, metadata
